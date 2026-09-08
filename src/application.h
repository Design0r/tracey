#pragma once

#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

#include "store.h"

class Application {
	GLFWwindow *window = nullptr;
	Store &store;

public:
	explicit Application(Store &s);
	~Application();
	void run() const;

private:
	int glfw_init();
	void glfw_close() const;
	void imgui_init() const;
	static void imgui_close();
};
