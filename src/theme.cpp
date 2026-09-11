#include "theme.h"

#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <vector>
#include <imgui.h>

static ImVec4 rgb(uint32_t hex, float a = 1.0f) {
	return ImVec4(
		static_cast<float>((hex >> 16) & 0xFF) / 255.0f,
		static_cast<float>((hex >> 8) & 0xFF) / 255.0f,
		static_cast<float>(hex & 0xFF) / 255.0f,
		a);
}

void theme::apply() {
	ImGui::StyleColorsDark(); // baseline for any color not overridden below

	ImGuiStyle &style = ImGui::GetStyle();

	// Spacing
	style.WindowPadding = ImVec2(12.0f, 12.0f);
	style.FramePadding = ImVec2(8.0f, 6.0f);
	style.ItemSpacing = ImVec2(8.0f, 8.0f);
	style.ItemInnerSpacing = ImVec2(6.0f, 6.0f);
	style.CellPadding = ImVec2(8.0f, 6.0f);
	style.IndentSpacing = 20.0f;
	style.ScrollbarSize = 12.0f;
	style.GrabMinSize = 10.0f;

	// Rounding
	style.WindowRounding = 8.0f;
	style.ChildRounding = 6.0f;
	style.FrameRounding = 6.0f;
	style.PopupRounding = 6.0f;
	style.ScrollbarRounding = 12.0f;
	style.GrabRounding = 6.0f;
	style.TabRounding = 6.0f;

	// Borders: outline containers, keep widgets flat
	style.WindowBorderSize = 1.0f;
	style.ChildBorderSize = 1.0f;
	style.PopupBorderSize = 1.0f;
	style.FrameBorderSize = 0.0f;
	style.TabBorderSize = 0.0f;
	style.TabBarBorderSize = 1.0f;
	style.TabBarOverlineSize = 2.0f;
	style.SeparatorTextBorderSize = 1.0f;

	// Palette
	const ImVec4 bg_base = rgb(0x131418);    // window background
	const ImVec4 bg_panel = rgb(0x1A1B20);   // title bars, menu bars, tabs
	const ImVec4 bg_popup = rgb(0x1C1D22);
	const ImVec4 frame = rgb(0x26272E);      // inputs, buttons
	const ImVec4 frame_hov = rgb(0x2F3139);
	const ImVec4 frame_act = rgb(0x393B45);
	const ImVec4 header = rgb(0x292B33);     // collapsing headers, selected items
	const ImVec4 header_hov = rgb(0x32343D);
	const ImVec4 header_act = rgb(0x3B3E48);
	const ImVec4 border = rgb(0x2A2C33);
	const ImVec4 text = rgb(0xE4E5E9);
	const ImVec4 text_dim = rgb(0x7D808B);
	const ImVec4 accent = rgb(0x5B8CFF);
	const ImVec4 accent_hov = rgb(0x7AA2FF);
	const ImVec4 clear = rgb(0x000000, 0.0f);

	ImVec4 *c = style.Colors;

	c[ImGuiCol_Text] = text;
	c[ImGuiCol_TextDisabled] = text_dim;
	c[ImGuiCol_TextLink] = accent_hov;
	c[ImGuiCol_TextSelectedBg] = rgb(0x5B8CFF, 0.35f);
	c[ImGuiCol_InputTextCursor] = text;

	c[ImGuiCol_WindowBg] = bg_base;
	c[ImGuiCol_ChildBg] = clear;
	c[ImGuiCol_PopupBg] = bg_popup;
	c[ImGuiCol_MenuBarBg] = bg_panel;
	c[ImGuiCol_Border] = border;
	c[ImGuiCol_BorderShadow] = clear;

	c[ImGuiCol_TitleBg] = bg_base;
	c[ImGuiCol_TitleBgActive] = bg_panel;
	c[ImGuiCol_TitleBgCollapsed] = bg_base;

	c[ImGuiCol_FrameBg] = frame;
	c[ImGuiCol_FrameBgHovered] = frame_hov;
	c[ImGuiCol_FrameBgActive] = frame_act;

	c[ImGuiCol_Button] = frame;
	c[ImGuiCol_ButtonHovered] = frame_hov;
	c[ImGuiCol_ButtonActive] = frame_act;

	c[ImGuiCol_Header] = header;
	c[ImGuiCol_HeaderHovered] = header_hov;
	c[ImGuiCol_HeaderActive] = header_act;

	c[ImGuiCol_CheckMark] = accent;
	c[ImGuiCol_SliderGrab] = accent;
	c[ImGuiCol_SliderGrabActive] = accent_hov;

	c[ImGuiCol_ScrollbarBg] = clear;
	c[ImGuiCol_ScrollbarGrab] = rgb(0x3A3D47);
	c[ImGuiCol_ScrollbarGrabHovered] = rgb(0x4A4E5A);
	c[ImGuiCol_ScrollbarGrabActive] = rgb(0x5A5F6D);

	c[ImGuiCol_Separator] = border;
	c[ImGuiCol_SeparatorHovered] = rgb(0x5B8CFF, 0.7f);
	c[ImGuiCol_SeparatorActive] = accent;

	c[ImGuiCol_ResizeGrip] = clear;
	c[ImGuiCol_ResizeGripHovered] = rgb(0x5B8CFF, 0.6f);
	c[ImGuiCol_ResizeGripActive] = accent;

	c[ImGuiCol_Tab] = bg_panel;
	c[ImGuiCol_TabHovered] = frame_hov;
	c[ImGuiCol_TabSelected] = frame;
	c[ImGuiCol_TabSelectedOverline] = accent;
	c[ImGuiCol_TabDimmed] = bg_panel;
	c[ImGuiCol_TabDimmedSelected] = rgb(0x212228);
	c[ImGuiCol_TabDimmedSelectedOverline] = clear;

	c[ImGuiCol_DockingPreview] = rgb(0x5B8CFF, 0.4f);
	c[ImGuiCol_DockingEmptyBg] = bg_base;

	c[ImGuiCol_PlotLines] = accent;
	c[ImGuiCol_PlotLinesHovered] = accent_hov;
	c[ImGuiCol_PlotHistogram] = accent;
	c[ImGuiCol_PlotHistogramHovered] = accent_hov;

	c[ImGuiCol_TableHeaderBg] = bg_panel;
	c[ImGuiCol_TableBorderStrong] = border;
	c[ImGuiCol_TableBorderLight] = rgb(0x212228);
	c[ImGuiCol_TableRowBg] = clear;
	c[ImGuiCol_TableRowBgAlt] = rgb(0xFFFFFF, 0.02f);

	c[ImGuiCol_TreeLines] = border;
	c[ImGuiCol_DragDropTarget] = accent;
	c[ImGuiCol_NavCursor] = accent;
	c[ImGuiCol_NavWindowingHighlight] = rgb(0xFFFFFF, 0.7f);
	c[ImGuiCol_NavWindowingDimBg] = rgb(0x000000, 0.5f);
	c[ImGuiCol_ModalWindowDimBg] = rgb(0x000000, 0.55f);
}

struct FontCandidate {
	std::filesystem::path path;
	float size; // SF/Helvetica run larger than Segoe UI at the same pixel size
};

// Ordered by preference; the first one that exists and loads wins.
static std::vector<FontCandidate> ui_font_candidates() {
#if defined(_WIN32)
	const char *windir = std::getenv("WINDIR");
	return {
		{std::filesystem::path(windir ? windir : "C:\\Windows") / "Fonts" / "segoeui.ttf", 16.0f},
	};
#elif defined(__APPLE__)
	return {
		{"/System/Library/Fonts/SFNS.ttf", 15.0f},     // San Francisco, macOS 11+
		{"/System/Library/Fonts/SFNSText.ttf", 15.0f}, // San Francisco, macOS 10.11 - 10.15
		{"/System/Library/Fonts/Helvetica.ttc", 15.0f},
	};
#else
	return {};
#endif
}

void theme::load_fonts() {
	ImGuiIO &io = ImGui::GetIO();
	for (const FontCandidate &font : ui_font_candidates()) {
		if (!std::filesystem::exists(font.path))
			continue;

		if (io.Fonts->AddFontFromFileTTF(font.path.string().c_str(), font.size)) {
			ImGui::GetStyle().FontSizeBase = font.size;
			return;
		}
	}
}
