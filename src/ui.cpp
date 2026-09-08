#include "ui.h"

#include <imgui.h>
#include <print>
#include <glad/glad.h>

#include <glad/glad.h>

#include <imgui.h>
#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>

static void framebuffer_size_callback(GLFWwindow *window, int width, int height) {
	glViewport(0, 0, width, height);
}

static bool Splitter(const char *id, float *a, float *b,
                     float min_a, float min_b, float thickness, float height) {
	ImGui::PushID(id);
	ImGui::InvisibleButton("##sp", ImVec2(thickness, height));
	bool active = ImGui::IsItemActive();
	bool hovered = ImGui::IsItemHovered();
	if (active || hovered) ImGui::SetMouseCursor(ImGuiMouseCursor_ResizeEW);
	if (active) {
		float d = ImGui::GetIO().MouseDelta.x;
		if (*a + d < min_a) d = min_a - *a;
		if (*b - d < min_b) d = *b - min_b;
		*a += d;
		*b -= d;
	}
	ImGui::GetWindowDrawList()->AddRectFilled(
		ImGui::GetItemRectMin(), ImGui::GetItemRectMax(),
		ImGui::GetColorU32(active
			                   ? ImGuiCol_SeparatorActive
			                   : hovered
				                     ? ImGuiCol_SeparatorHovered
				                     : ImGuiCol_Separator));
	ImGui::PopID();
	return active;
}

void ui(const Store &s) {
	static float wL = 250.0f, wC = 500.0f;
	const float th = 6.0f, minw = 80.0f;

	ImGuiViewport *vp = ImGui::GetMainViewport();
	ImGui::SetNextWindowPos(vp->WorkPos);
	ImGui::SetNextWindowSize(vp->WorkSize);
	ImGui::Begin("##root", nullptr,
	             ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
	             ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoBringToFrontOnFocus);

	ImVec2 avail = ImGui::GetContentRegionAvail();
	float wR = avail.x - wL - wC - th * 2.0f;
	if (wR < minw) {
		wC += wR - minw;
		wR = minw;
	} // clamp on window shrink
	if (wC < minw) {
		wL += wC - minw;
		wC = minw;
	}
	if (wL < minw) wL = minw;

	ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(0, 0));
	ImGui::BeginChild("left", ImVec2(wL, avail.y), ImGuiChildFlags_Borders);
	ImGui::TextUnformatted("left");
	ImGui::EndChild();

	ImGui::SameLine();
	Splitter("s0", &wL, &wC, minw, minw, th, avail.y);
	ImGui::SameLine();

	ImGui::BeginChild("center", ImVec2(wC, avail.y), ImGuiChildFlags_Borders);
	ImGui::TextUnformatted("center");
	ImGui::EndChild();

	ImGui::SameLine();
	Splitter("s1", &wC, &wR, minw, minw, th, avail.y);
	ImGui::SameLine();

	ImGui::BeginChild("right", ImVec2(wR, avail.y), ImGuiChildFlags_Borders);
	ImGui::TextUnformatted("right");
	ImGui::EndChild();
	ImGui::PopStyleVar();

	ImGui::End();
}

static void key_callback(GLFWwindow *window, int key, int scancode, int action,
                         int mods) {
	if (key == GLFW_KEY_ESCAPE && action == GLFW_PRESS)
		glfwSetWindowShouldClose(window, GLFW_TRUE);
}

void Ui::run() {
	while (!glfwWindowShouldClose(window)) {
		glfwPollEvents();
		render_frame();
	}
}

Ui::Ui() {
	glfw_init();
	imgui_init();
}

Ui::~Ui() {
	imgui_close();
	glfw_close();
}

int Ui::glfw_init() {
	glfwInit();
	glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
	glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
	glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
#ifdef __APPLE__
	glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GL_TRUE);
#endif

	window = glfwCreateWindow(800, 600, "glfw window", nullptr, nullptr);
	if (!window) {
		std::println("failed ot create GLFW window");
		glfwTerminate();
		return -1;
	}

	glfwMakeContextCurrent(window);
	glfwSetFramebufferSizeCallback(window, framebuffer_size_callback);
	glfwSetKeyCallback(window, key_callback);
	glfwSwapInterval(1);


	if (!gladLoadGL()) {
		std::println("failed to initialize GLAD");
		glfwTerminate();
		return -1;
	}

	return 0;
}

void Ui::glfw_close() const {
	glfwDestroyWindow(window);
	glfwTerminate();
}

void Ui::imgui_init() const {
	IMGUI_CHECKVERSION();
	ImGui::CreateContext();
	ImGuiIO &io = ImGui::GetIO();
	io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
	io.ConfigFlags |= ImGuiConfigFlags_DockingEnable;
	ImGui::StyleColorsDark();

	float x, y;
	glfwGetWindowContentScale(window, &x, &y);
	ImGuiStyle &style = ImGui::GetStyle();
	style.ScaleAllSizes(x);
	style.FontScaleDpi = x;

	ImGui_ImplGlfw_InitForOpenGL(window, true);
	ImGui_ImplOpenGL3_Init();
}

void Ui::imgui_close() {
	ImGui_ImplOpenGL3_Shutdown();
	ImGui_ImplGlfw_Shutdown();
	ImGui::DestroyContext();
}

void Ui::render_frame() {
	glClearColor(0.2f, 0.2f, 0.2f, 1.0f);
	glClear(GL_COLOR_BUFFER_BIT);

	ImGui_ImplGlfw_NewFrame();
	ImGui_ImplOpenGL3_NewFrame();
	ImGui::NewFrame();

	ImGui::ShowDemoWindow(nullptr);

	ImGui::Render();
	int w, h;
	glfwGetFramebufferSize(window, &w, &h);
	if (w <= 0 || h <= 0) return; // minimized
	glViewport(0, 0, w, h);
	glClear(GL_COLOR_BUFFER_BIT);
	ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());

	if (ImGui::GetIO().ConfigFlags & ImGuiConfigFlags_ViewportsEnable) {
		GLFWwindow *backup = glfwGetCurrentContext();
		ImGui::UpdatePlatformWindows();
		ImGui::RenderPlatformWindowsDefault();
		glfwMakeContextCurrent(backup);
	}

	glfwSwapBuffers(window);
}
