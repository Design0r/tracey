#pragma once
#include "store.h"

#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

class Ui {
	GLFWwindow *window = nullptr;

public:
	Ui();
	~Ui();

	void run();

private:
	int glfw_init();
	void glfw_close() const;
	void imgui_init() const;
	static void imgui_close();
	void render_frame();
};

void ui(const Store &s);
