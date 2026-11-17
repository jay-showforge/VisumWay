#pragma once

#include <UIAutomation.h>
#include <oleauto.h>

#include <sstream>
#include <string>
#include <string_view>
#include <utility>

namespace controls {

std::wstring query_from_stdin() {
    std::string query;
    std::getline(std::cin, query);
    if (query.empty()) return {};
    if (query.size() > 640 || query.find('\0') != query.npos) throw std::runtime_error("Invalid control name.");
    const int bytes = static_cast<int>(query.size());
    const int units = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, query.data(), bytes, nullptr, 0);
    if (units < 1 || units > 160) throw std::runtime_error("Invalid control name.");
    std::wstring wide(units, L'\0');
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, query.data(), bytes, wide.data(), units) != units) {
        throw std::runtime_error("Invalid control name.");
    }
    return wide;
}

void json_string(std::ostream& out, std::wstring_view value) {
    value = value.substr(0, 160);
    const int units = static_cast<int>(value.size());
    const int bytes = WideCharToMultiByte(CP_UTF8, 0, value.data(), units, nullptr, 0, nullptr, nullptr);
    std::string utf8(bytes, '\0');
    if (bytes) WideCharToMultiByte(CP_UTF8, 0, value.data(), units, utf8.data(), bytes, nullptr, nullptr);
    out << '"';
    for (const unsigned char ch : utf8) {
        if (ch == '"' || ch == '\\') out << '\\' << ch;
        else if (ch < 32) out << "\\u00" << "0123456789abcdef"[ch >> 4] << "0123456789abcdef"[ch & 15];
        else out << ch;
    }
    out << '"';
}

struct Variant {
    VARIANT value{};
    ~Variant() { VariantClear(&value); }
};

void string_property(std::ostream& out, IUIAutomationElement* element, PROPERTYID property) {
    Variant field;
    if (SUCCEEDED(element->GetCachedPropertyValueEx(property, TRUE, &field.value)) &&
        field.value.vt == VT_BSTR && field.value.bstrVal) {
        json_string(out, {field.value.bstrVal, SysStringLen(field.value.bstrVal)});
    } else {
        out << "\"\"";
    }
}

void optional_state(std::ostream& out, IUIAutomationElement* element, PROPERTYID property, const char* name) {
    Variant state;
    if (FAILED(element->GetCachedPropertyValueEx(property, TRUE, &state.value))) return;
    if (state.value.vt == VT_BOOL) {
        out << ",\"" << name << "\":" << (state.value.boolVal ? "true" : "false");
    } else if (state.value.vt == VT_I4 && 0 <= state.value.lVal && state.value.lVal <= 2) {
        const char* choices[] = {"off", "on", "indeterminate"};
        out << ",\"" << name << "\":\"" << choices[state.value.lVal] << '"';
    }
}

bool row(std::ostream& out, IUIAutomationElement* element, unsigned depth) {
    BOOL password = FALSE;
    // Treat inability to read the password state as sensitive.
    const bool protected_name = FAILED(element->get_CachedIsPassword(&password)) || password;
    out << "{\"name\":";
    if (protected_name) out << "\"\"";
    else string_property(out, element, UIA_NamePropertyId);
    out << ",\"role\":";
    string_property(out, element, UIA_LocalizedControlTypePropertyId);
    out << ",\"depth\":" << depth;
    if (protected_name) out << ",\"protected\":true";
    optional_state(out, element, UIA_IsEnabledPropertyId, "enabled");
    optional_state(out, element, UIA_IsOffscreenPropertyId, "offscreen");
    optional_state(out, element, UIA_HasKeyboardFocusPropertyId, "focused");
    optional_state(out, element, UIA_SelectionItemIsSelectedPropertyId, "selected");
    optional_state(out, element, UIA_ToggleToggleStatePropertyId, "toggle");
    RECT bounds{};
    if (SUCCEEDED(element->get_CachedBoundingRectangle(&bounds)) &&
        bounds.right > bounds.left && bounds.bottom > bounds.top) {
        out << ",\"bounds\":{\"x\":" << bounds.left << ",\"y\":" << bounds.top
            << ",\"width\":" << bounds.right - bounds.left << ",\"height\":" << bounds.bottom - bounds.top << '}';
    }
    out << '}';
    return protected_name;
}

struct Walk {
    IUIAutomationTreeWalker* walker;
    IUIAutomationCacheRequest* cache;
    unsigned limit;
    unsigned count = 0;
    bool truncated = false;

    void children(std::ostream& out, IUIAutomationElement* parent, unsigned depth) {
        if (depth > 12) {
            truncated = true;
            return;
        }
        winrt::com_ptr<IUIAutomationElement> element;
        winrt::check_hresult(walker->GetFirstChildElementBuildCache(parent, cache, element.put()));
        while (element) {
            if (count == limit) {
                truncated = true;
                return;
            }
            if (count++) out << ',';
            if (!row(out, element.get(), depth)) children(out, element.get(), depth + 1);
            if (count == limit && truncated) return;
            winrt::com_ptr<IUIAutomationElement> sibling;
            winrt::check_hresult(walker->GetNextSiblingElementBuildCache(element.get(), cache, sibling.put()));
            element = std::move(sibling);
        }
    }
};

std::string inspect(HWND hwnd, DWORD pid, unsigned limit, const wchar_t* exact_name) {
    auto automation = winrt::create_instance<IUIAutomation>(__uuidof(CUIAutomation));
    winrt::com_ptr<IUIAutomationCacheRequest> cache;
    winrt::check_hresult(automation->CreateCacheRequest(cache.put()));
    for (auto property : {UIA_NamePropertyId, UIA_LocalizedControlTypePropertyId, UIA_ProcessIdPropertyId,
                          UIA_IsEnabledPropertyId, UIA_IsOffscreenPropertyId, UIA_IsPasswordPropertyId,
                          UIA_HasKeyboardFocusPropertyId, UIA_BoundingRectanglePropertyId,
                          UIA_SelectionItemIsSelectedPropertyId, UIA_ToggleToggleStatePropertyId}) {
        winrt::check_hresult(cache->AddProperty(property));
    }
    winrt::com_ptr<IUIAutomationElement> root;
    winrt::check_hresult(automation->ElementFromHandleBuildCache(hwnd, cache.get(), root.put()));
    int reported_pid = 0;
    if (!root || FAILED(root->get_CachedProcessId(&reported_pid)) || static_cast<DWORD>(reported_pid) != pid) {
        throw std::runtime_error("UI Automation could not identify the selected window.");
    }
    std::ostringstream out;
    out << "{\"pid\":" << pid << ",\"title\":";
    string_property(out, root.get(), UIA_NamePropertyId);
    out << ",\"controls\":[";
    bool truncated = false;
    if (exact_name) {
        Variant value;
        value.value.vt = VT_BSTR;
        value.value.bstrVal = SysAllocString(exact_name);
        if (!value.value.bstrVal) throw std::bad_alloc();
        winrt::com_ptr<IUIAutomationCondition> condition;
        winrt::check_hresult(automation->CreatePropertyConditionEx(UIA_NamePropertyId, value.value,
            PropertyConditionFlags_IgnoreCase, condition.put()));
        winrt::com_ptr<IUIAutomationElement> hit;
        winrt::check_hresult(root->FindFirstBuildCache(TreeScope_Subtree, condition.get(), cache.get(), hit.put()));
        if (hit) row(out, hit.get(), 0);
    } else {
        winrt::com_ptr<IUIAutomationTreeWalker> walker;
        winrt::check_hresult(automation->get_ControlViewWalker(walker.put()));
        Walk walk{walker.get(), cache.get(), limit};
        walk.children(out, root.get(), 1);
        truncated = walk.truncated;
    }
    out << "],\"truncated\":" << (truncated ? "true" : "false") << '}';
    return out.str();
}

} // namespace controls
