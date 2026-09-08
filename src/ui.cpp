#include "ui.h"

#include <imgui.h>
#include <print>

void ui(const Store &s) {
	ImGui::Begin("main");
	if (ImGui::Button("print")) {
		auto profiles = s.get_profiles();
		for (auto const &p: profiles) {
			std::println("id: {}", p.id);
		}
	};
	ImGui::End();
}
