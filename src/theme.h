#pragma once

namespace theme {
	// Applies the Luma color palette and widget geometry to the current ImGui context.
	// Call before ImGuiStyle::ScaleAllSizes() so DPI scaling is applied on top.
	void apply();

	// Loads the platform UI font (Segoe UI on Windows). Keeps ImGui's built-in font if unavailable.
	void load_fonts();
}
