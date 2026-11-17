#include <windows.h>
#include <d3d11.h>
#include <dwmapi.h>
#include <wincodec.h>
#include <windows.graphics.capture.interop.h>
#include <windows.graphics.directx.direct3d11.interop.h>
#include <winrt/Windows.Foundation.Metadata.h>
#include <winrt/Windows.Graphics.Capture.h>
#include <winrt/Windows.Graphics.DirectX.Direct3D11.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdint>
#include <fcntl.h>
#include <iostream>
#include <io.h>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>

#include "controls.h"

namespace capture = winrt::Windows::Graphics::Capture;
namespace dx = winrt::Windows::Graphics::DirectX;

bool interactive_desktop() {
    auto desktop = OpenInputDesktop(0, FALSE, DESKTOP_READOBJECTS);
    if (!desktop) return false;
    wchar_t input[256]{}, current[256]{};
    bool readable = GetUserObjectInformationW(desktop, UOI_NAME, input, sizeof(input), nullptr);
    CloseDesktop(desktop);
    return readable &&
        GetUserObjectInformationW(GetThreadDesktop(GetCurrentThreadId()), UOI_NAME, current, sizeof(current), nullptr) &&
        std::wstring_view(input) == current;
}

bool window_target(HWND hwnd, DWORD& pid, RECT& bounds) {
    if (GetAncestor(hwnd, GA_ROOT) != hwnd || !IsWindowVisible(hwnd) || IsIconic(hwnd) ||
        !GetWindowTextLengthW(hwnd) ||
        (GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW)) return false;
    DWORD cloaked = 0, affinity = 0;
    if (SUCCEEDED(DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, &cloaked, sizeof(cloaked))) && cloaked) {
        return false;
    }
    if (GetWindowDisplayAffinity(hwnd, &affinity) && affinity != WDA_NONE) return false;
    pid = 0;
    GetWindowThreadProcessId(hwnd, &pid);
    if (FAILED(DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, &bounds, sizeof(bounds))) &&
        !GetWindowRect(hwnd, &bounds)) return false;
    return pid && bounds.right > bounds.left && bounds.bottom > bounds.top;
}

void print_bounds(const RECT& r) {
    std::cout << ",\"bounds\":{\"x\":" << r.left << ",\"y\":" << r.top
              << ",\"width\":" << r.right - r.left << ",\"height\":" << r.bottom - r.top << '}';
}

struct Listing {
    unsigned count = 0;
    HWND foreground = GetForegroundWindow();

    bool emit() {
        if (count == 512) return false;
        if (count++) std::cout << ',';
        return true;
    }
};

BOOL CALLBACK list_display(HMONITOR monitor, HDC, LPRECT, LPARAM context) {
    MONITORINFO info{};
    info.cbSize = sizeof(info);
    if (!GetMonitorInfoW(monitor, &info)) return TRUE;
    if (!reinterpret_cast<Listing*>(context)->emit()) return FALSE;
    std::cout << "{\"id\":\"display:" << reinterpret_cast<std::uintptr_t>(monitor)
              << "\",\"kind\":\"display\",\"primary\":"
              << (info.dwFlags & MONITORINFOF_PRIMARY ? "true" : "false");
    print_bounds(info.rcMonitor);
    std::cout << '}';
    return TRUE;
}

BOOL CALLBACK list_window(HWND hwnd, LPARAM context) {
    DWORD pid;
    RECT bounds;
    if (!window_target(hwnd, pid, bounds)) return TRUE;
    auto& listing = *reinterpret_cast<Listing*>(context);
    if (!listing.emit()) return FALSE;
    std::cout << "{\"id\":\"window:" << reinterpret_cast<std::uintptr_t>(hwnd) << ':' << pid
              << "\",\"kind\":\"window\",\"pid\":" << pid
              << ",\"foreground\":" << (listing.foreground == hwnd ? "true" : "false");
    print_bounds(bounds);
    std::cout << '}';
    return TRUE;
}

std::uint64_t number(std::wstring_view text) {
    if (text.empty() || text.size() > 20 || text.find_first_not_of(L"0123456789") != text.npos) {
        throw std::runtime_error("Invalid target or size. List capture targets again.");
    }
    return std::stoull(std::wstring(text));
}

struct Target {
    HWND window = nullptr;
    HMONITOR display = nullptr;
    std::uint64_t pid = 0;

    void check() const {
        if (window) {
            RECT bounds;
            DWORD actual;
            if (!window_target(window, actual, bounds) || actual != pid) {
                throw std::runtime_error("Window is unavailable, protected, or changed. List targets again.");
            }
        } else {
            MONITORINFO info{};
            info.cbSize = sizeof(info);
            if (!GetMonitorInfoW(display, &info)) {
                throw std::runtime_error("Display is unavailable. List targets again.");
            }
        }
    }
};

Target parse_target(std::wstring_view id) {
    Target target;
    if (id.substr(0, 8) == L"display:") {
        target.display = reinterpret_cast<HMONITOR>(static_cast<std::uintptr_t>(number(id.substr(8))));
    } else if (id.substr(0, 7) == L"window:") {
        const auto separator = id.find(L':', 7);
        if (separator == id.npos) throw std::runtime_error("Window target requires a process ID.");
        target.window = reinterpret_cast<HWND>(static_cast<std::uintptr_t>(number(id.substr(7, separator - 7))));
        target.pid = number(id.substr(separator + 1));
    }
    if (!target.window && !target.display) throw std::runtime_error("Unknown capture target.");
    target.check();
    return target;
}

void encode_png(ID3D11DeviceContext* context, ID3D11Texture2D* texture, UINT width, UINT height,
                UINT max_edge, IWICImagingFactory* factory, IWICStream* stream) {
    D3D11_MAPPED_SUBRESOURCE mapped{};
    winrt::check_hresult(context->Map(texture, 0, D3D11_MAP_READ, 0, &mapped));
    struct Unmap {
        ID3D11DeviceContext* context;
        ID3D11Texture2D* texture;
        ~Unmap() { context->Unmap(texture, 0); }
    } unmap{context, texture};

    winrt::com_ptr<IWICBitmap> bitmap;
    winrt::check_hresult(factory->CreateBitmapFromMemory(width, height, GUID_WICPixelFormat32bppBGR,
        mapped.RowPitch, mapped.RowPitch * height, static_cast<BYTE*>(mapped.pData), bitmap.put()));
    auto image = bitmap.as<IWICBitmapSource>();
    const UINT largest = std::max(width, height);
    if (largest > max_edge) {
        winrt::com_ptr<IWICBitmapScaler> scaler;
        winrt::check_hresult(factory->CreateBitmapScaler(scaler.put()));
        width = std::max(1u, width * max_edge / largest);
        height = std::max(1u, height * max_edge / largest);
        winrt::check_hresult(scaler->Initialize(image.get(), width, height, WICBitmapInterpolationModeFant));
        image = scaler.as<IWICBitmapSource>();
    }

    winrt::com_ptr<IWICBitmapEncoder> encoder;
    winrt::check_hresult(factory->CreateEncoder(GUID_ContainerFormatPng, nullptr, encoder.put()));
    winrt::check_hresult(encoder->Initialize(stream, WICBitmapEncoderNoCache));
    winrt::com_ptr<IWICBitmapFrameEncode> output;
    winrt::check_hresult(encoder->CreateNewFrame(output.put(), nullptr));
    winrt::check_hresult(output->Initialize(nullptr));
    winrt::check_hresult(output->SetSize(width, height));
    WICPixelFormatGUID format = GUID_WICPixelFormat24bppBGR;
    winrt::check_hresult(output->SetPixelFormat(&format));
    winrt::com_ptr<IWICFormatConverter> converter;
    winrt::check_hresult(factory->CreateFormatConverter(converter.put()));
    winrt::check_hresult(converter->Initialize(image.get(), format, WICBitmapDitherTypeNone,
                                             nullptr, 0, WICBitmapPaletteTypeCustom));
    winrt::check_hresult(output->WriteSource(converter.get(), nullptr));
    winrt::check_hresult(output->Commit());
    winrt::check_hresult(encoder->Commit());
}

bool valid_size(winrt::Windows::Graphics::SizeInt32 size) {
    return size.Width > 0 && size.Height > 0 && size.Width <= 16384 && size.Height <= 16384 &&
        static_cast<std::int64_t>(size.Width) * size.Height <= 64000000;
}

void emit_frame(IStream* memory, const char* renderer, std::int64_t elapsed_ms) {
    STATSTG info{};
    winrt::check_hresult(memory->Stat(&info, STATFLAG_NONAME));
    const auto length = info.cbSize.QuadPart;
    if (!length || length > 6 * 1024 * 1024) throw std::runtime_error("Frame exceeds the feed byte limit.");
    HGLOBAL storage = nullptr;
    winrt::check_hresult(GetHGlobalFromStream(memory, &storage));
    const auto bytes = static_cast<const char*>(GlobalLock(storage));
    if (!bytes) throw std::runtime_error("Could not read the encoded frame.");
    std::cout << "{\"bytes\":" << length << ",\"renderer\":\"" << renderer
              << "\",\"elapsed_ms\":" << elapsed_ms << "}\n";
    std::cout.write(bytes, static_cast<std::streamsize>(length));
    std::cout.flush();
    GlobalUnlock(storage);
}

void capture_frames(const Target& target, UINT max_edge, const wchar_t* path, bool force_software,
                    unsigned lease_seconds = 0, unsigned fps = 0) {
    if (!capture::GraphicsCaptureSession::IsSupported()) {
        throw std::runtime_error("Windows Graphics Capture is unavailable in this desktop session.");
    }
    const auto access = winrt::get_activation_factory<capture::GraphicsCaptureItem, IGraphicsCaptureItemInterop>();
    capture::GraphicsCaptureItem item{nullptr};
    const auto interface_id = winrt::guid_of<capture::IGraphicsCaptureItem>();
    winrt::check_hresult(target.window
        ? access->CreateForWindow(target.window, interface_id, winrt::put_abi(item))
        : access->CreateForMonitor(target.display, interface_id, winrt::put_abi(item)));

    auto size = item.Size();
    if (!valid_size(size)) {
        throw std::runtime_error("Target has unavailable or oversized dimensions.");
    }
    winrt::com_ptr<ID3D11Device> device;
    winrt::com_ptr<ID3D11DeviceContext> context;
    auto create_device = [&](D3D_DRIVER_TYPE type) {
        device = nullptr;
        context = nullptr;
        return D3D11CreateDevice(nullptr, type, nullptr, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                                 nullptr, 0, D3D11_SDK_VERSION, device.put(), nullptr, context.put());
    };
    bool software = force_software || FAILED(create_device(D3D_DRIVER_TYPE_HARDWARE));
    if (software) winrt::check_hresult(create_device(D3D_DRIVER_TYPE_WARP));
    winrt::com_ptr<IInspectable> inspectable;
    winrt::check_hresult(CreateDirect3D11DeviceFromDXGIDevice(device.as<IDXGIDevice>().get(), inspectable.put()));
    const auto graphics_device = inspectable.as<dx::Direct3D11::IDirect3DDevice>();
    const auto format = dx::DirectXPixelFormat::B8G8R8A8UIntNormalized;
    const int buffers = fps ? 2 : 1;
    auto pool = capture::Direct3D11CaptureFramePool::CreateFreeThreaded(graphics_device, format, buffers, size);
    auto session = pool.CreateCaptureSession(item);
    using winrt::Windows::Foundation::Metadata::ApiInformation;
    if (ApiInformation::IsPropertyPresent(L"Windows.Graphics.Capture.GraphicsCaptureSession", L"IsCursorCaptureEnabled")) {
        session.IsCursorCaptureEnabled(false);
    }
    const char* renderer = software ? "warp" : "d3d11";
    auto factory = winrt::create_instance<IWICImagingFactory>(CLSID_WICImagingFactory);
    winrt::com_ptr<ID3D11Texture2D> staging;
    const auto started = std::chrono::steady_clock::now();
    const auto first_frame_deadline = started + std::chrono::seconds(4);
    const auto deadline = fps ? started + std::chrono::seconds(lease_seconds) : first_frame_deadline;
    const auto period = std::chrono::milliseconds(fps ? 1000 / fps : 15);
    auto last_output = started;
    bool sent = false;
    session.StartCapture();
    while (std::chrono::steady_clock::now() < deadline) {
        if (fps && !PeekNamedPipe(GetStdHandle(STD_INPUT_HANDLE), nullptr, 0, nullptr, nullptr, nullptr)) return;
        target.check();
        if (!interactive_desktop()) throw std::runtime_error("Input desktop changed during capture.");
        auto frame = pool.TryGetNextFrame();
        if (!frame) {
            const auto now = std::chrono::steady_clock::now();
            if (!sent && now >= first_frame_deadline) break;
            if (fps && now - last_output >= std::chrono::milliseconds(500)) {
                std::cout << "{\"bytes\":0}\n" << std::flush;
                if (!std::cout) return;
                last_output = now;
            }
            std::this_thread::sleep_for(std::min(period, std::chrono::milliseconds(10)));
            continue;
        }
        const auto sampled = std::chrono::steady_clock::now();
        // Consume the fresher of the pool's two available frames.
        if (fps) {
            auto newer = pool.TryGetNextFrame();
            if (newer) {
                frame.Close();
                frame = std::move(newer);
            }
        }
        const auto dimensions = frame.ContentSize();
        if (!valid_size(dimensions)) throw std::runtime_error("Target has unavailable or oversized dimensions.");
        if (dimensions.Width != size.Width || dimensions.Height != size.Height) {
            if (!fps && dimensions.Width <= size.Width && dimensions.Height <= size.Height) {
                size = dimensions;
            } else if (!fps) {
                throw std::runtime_error("Target resized during capture. Request another frame.");
            } else {
                frame.Close();
                size = dimensions;
                staging = nullptr;
                pool.Recreate(graphics_device, format, buffers, size);
                continue;
            }
        }
        const UINT width = static_cast<UINT>(size.Width), height = static_cast<UINT>(size.Height);
        if (!staging) {
            D3D11_TEXTURE2D_DESC desc{};
            desc.Width = width;
            desc.Height = height;
            desc.MipLevels = desc.ArraySize = desc.SampleDesc.Count = 1;
            desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
            desc.Usage = D3D11_USAGE_STAGING;
            desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
            winrt::check_hresult(device->CreateTexture2D(&desc, nullptr, staging.put()));
        }
        auto surface = frame.Surface().as<::Windows::Graphics::DirectX::Direct3D11::IDirect3DDxgiInterfaceAccess>();
        winrt::com_ptr<ID3D11Texture2D> texture;
        winrt::check_hresult(surface->GetInterface(__uuidof(ID3D11Texture2D), texture.put_void()));
        D3D11_BOX region{0, 0, 0, width, height, 1};
        context->CopySubresourceRegion(staging.get(), 0, 0, 0, 0, texture.get(), 0, &region);
        frame.Close();
        winrt::com_ptr<IWICStream> stream;
        winrt::check_hresult(factory->CreateStream(stream.put()));
        winrt::com_ptr<IStream> memory;
        if (fps) {
            winrt::check_hresult(CreateStreamOnHGlobal(nullptr, TRUE, memory.put()));
            winrt::check_hresult(stream->InitializeFromIStream(memory.get()));
        } else {
            winrt::check_hresult(stream->InitializeFromFilename(path, GENERIC_WRITE));
        }
        encode_png(context.get(), staging.get(), width, height, max_edge, factory.get(), stream.get());
        if (!fps) {
            std::cout << "{\"renderer\":\"" << renderer << "\"}\n";
            return;
        }
        const auto now = std::chrono::steady_clock::now();
        if (now >= deadline) return;
        target.check();
        if (!interactive_desktop()) throw std::runtime_error("Input desktop changed during capture.");
        emit_frame(memory.get(), renderer,
                   std::chrono::duration_cast<std::chrono::milliseconds>(sampled - started).count());
        if (!std::cout) return;
        last_output = now;
        sent = true;
        std::this_thread::sleep_until(std::min(sampled + period, deadline));
    }
    if (!sent) throw std::runtime_error("Windows returned no frame. Check that the target is visible in the current session.");
}

int wmain(int argc, wchar_t** argv) {
    const std::wstring_view command = argc > 1 ? argv[1] : L"";
    try {
        if (command == L"--version" && argc == 2) {
            std::cout << "visumway-windows-visual 1\n";
            return 0;
        }
        if (!interactive_desktop()) throw std::runtime_error("An interactive Windows input desktop is required.");
        SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        if (command == L"targets" && argc == 2) {
            Listing listing;
            std::cout << "{\"features\":[\"window-feed\",\"window-controls\"],\"targets\":[";
            EnumDisplayMonitors(nullptr, nullptr, list_display, reinterpret_cast<LPARAM>(&listing));
            EnumWindows(list_window, reinterpret_cast<LPARAM>(&listing));
            std::cout << "]}\n";
            return 0;
        }
        if (command == L"capture" && (argc == 5 || (argc == 6 && std::wstring_view(argv[5]) == L"--software"))) {
            const auto limit = number(argv[3]);
            if (limit < 1 || limit > 4096) throw std::runtime_error("Maximum edge must be between 1 and 4096.");
            winrt::init_apartment(winrt::apartment_type::multi_threaded);
            capture_frames(parse_target(argv[2]), static_cast<UINT>(limit), argv[4], argc == 6);
            winrt::uninit_apartment();
            return 0;
        }
        if (command == L"feed" && argc == 6) {
            const auto target = parse_target(argv[2]);
            const auto limit = number(argv[3]), lease = number(argv[4]), fps = number(argv[5]);
            if (!target.window || limit < 1 || limit > 1280 || lease < 1 || lease > 600 || fps < 1 || fps > 10) {
                throw std::runtime_error("Expected a window, maximum edge 1-1280, lease 1-600, and rate 1-10.");
            }
            if (_setmode(_fileno(stdout), _O_BINARY) == -1) throw std::runtime_error("Could not open feed output.");
            winrt::init_apartment(winrt::apartment_type::multi_threaded);
            capture_frames(target, static_cast<UINT>(limit), nullptr, false,
                           static_cast<unsigned>(lease), static_cast<unsigned>(fps));
            winrt::uninit_apartment();
            return 0;
        }
        if (command == L"controls" && argc == 4) {
            const auto target = parse_target(argv[2]);
            const auto limit = number(argv[3]);
            if (!target.window || limit < 1 || limit > 64) {
                throw std::runtime_error("Expected a window selector and a limit of 1-64 controls.");
            }
            const auto query = controls::query_from_stdin();
            winrt::init_apartment(winrt::apartment_type::multi_threaded);
            const auto report = controls::inspect(target.window, static_cast<DWORD>(target.pid),
                static_cast<unsigned>(limit), query.empty() ? nullptr : query.c_str());
            winrt::uninit_apartment();
            target.check();
            if (!interactive_desktop()) throw std::runtime_error("Input desktop changed during inspection.");
            std::cout << report << '\n';
            return 0;
        }
        throw std::runtime_error("Usage: windows-visual targets | capture TARGET MAX_EDGE OUTPUT [--software] | feed WINDOW MAX_EDGE LEASE FPS | controls WINDOW LIMIT");
    } catch (const winrt::hresult_error& error) {
        std::cerr << (command == L"controls" ? "Windows UI Automation error 0x" : "Windows Graphics Capture error 0x") << std::hex
                  << static_cast<std::uint32_t>(error.code().value) << '\n';
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
    }
    return 1;
}
