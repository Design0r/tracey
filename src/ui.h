#pragma once
#include "store.h"

#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

struct UiState {
	ImageFormat selected_format;
};

class Ui {
	GLFWwindow *window = nullptr;
	ExportProfile selected_profile{};
	std::vector<ExportProfile> profiles;
	UiState state{};

	Store &store;

public:
	explicit Ui(Store &s);
	~Ui();

	void run();

private:
	int glfw_init();
	void glfw_close() const;
	void imgui_init() const;
	static void imgui_close();
	void render_frame();
};
