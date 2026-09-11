#include "ui.h"

#include <format>
#include <imgui.h>
#include <print>
#include <glad/glad.h>

#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>

static void framebuffer_size_callback(GLFWwindow *window, int width, int height) {
	glViewport(0, 0, width, height);
}

static void PropertyRow(const char *label) {
	ImGui::TableNextRow();
	ImGui::TableSetColumnIndex(0);
	ImGui::AlignTextToFramePadding(); // vertically center text with the widget
	ImGui::TextUnformatted(label);
	ImGui::TableSetColumnIndex(1);
	ImGui::SetNextItemWidth(-FLT_MIN); // fill the column
}

static void ui(ExportProfile &p, UiState &s) {
	ImGuiViewport *vp = ImGui::GetMainViewport();
	ImGui::SetNextWindowPos(vp->WorkPos);
	ImGui::SetNextWindowSize(vp->WorkSize);
	ImGui::Begin("##root", nullptr,
	             ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
	             ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoBringToFrontOnFocus);

	if (ImGui::Button("Open")) {
		/* ... */
	}
	ImGui::SameLine();
	if (ImGui::Button("Save Profile")) {
		/* ... */
	}
	ImGui::SameLine();
	if (ImGui::Button("Run Batch")) {
		/* ... */
	}
	ImGui::Separator();


	const ImGuiStyle &style = ImGui::GetStyle();
	const float status_h = ImGui::GetFrameHeight() + style.ItemSpacing.y * 2.0f + 1.0f;


	ImGui::BeginChild("##body", ImVec2(0, -status_h));
	{
		ImGui::Columns(3, nullptr, true);

		ImGui::BeginChild("left");
		ImGui::TextUnformatted("left");
		ImGui::SameLine();
		ImGui::Button("test btn");
		ImGui::EndChild();

		ImGui::NextColumn();

		ImGui::BeginChild("center");
		ImGui::TextUnformatted("Pipeline");
		ImGui::TextUnformatted(
			"Every file in the batch runs through these stages in order. The line tracks what each stage leaves behind.");
		if (ImGui::CollapsingHeader("Source")) {
		}

		if (ImGui::CollapsingHeader("Color")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);

				PropertyRow("Enabled");
				ImGui::Checkbox("Enabled", &p.color_space_enabled);

				PropertyRow("Color Profile");
				if (ImGui::BeginCombo("##ColorProfile", ImageFormatNames[p.color_space].data())) {
					for (int i = 0; i < std::size(ImageFormatNames); i++) {
						bool is_selected = p.color_space == i;
						if (ImGui::Selectable(ImageFormatNames[i].data(), is_selected)) {
							p.color_space = static_cast<ColorSpace>(i);
							std::println("{}", ImageFormatNames[p.color_space]);
						}

						if (is_selected) ImGui::SetItemDefaultFocus();
					}

					ImGui::EndCombo();
				}


				PropertyRow("Handling");
				for (int i = 0; i < std::size(ColorSpaceOpNames); i++) {
					if (ImGui::RadioButton(ColorSpaceOpNames[i].data(), p.color_space_op == i)) {
						p.color_space_op = static_cast<ColorSpaceOp>(i);
						std::println("{}", ColorSpaceOpNames[i]);
					}
					ImGui::SameLine();
				}
				ImGui::NewLine();

				ImGui::EndTable();
			}
		}

		if (ImGui::CollapsingHeader("Bit Depth")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);


				PropertyRow("Enabled");
				ImGui::Checkbox("Enabled", &p.bit_depth_enabled);

				PropertyRow("Bit Depth");
				for (int i = 0; i < std::size(BitDepthNames); i++) {
					if (ImGui::RadioButton(BitDepthNames[i].data(), p.bit_depth == i)) {
						p.bit_depth = static_cast<BitDepth>(i);
					}

					ImGui::SameLine();
				}

				ImGui::NewLine();


				PropertyRow("Alpha");
				if (ImGui::Checkbox("Keep Alpha Channel", &p.keep_alpha)) {
					std::println("Keep Alpha Channel: {}", p.keep_alpha);
				}

				ImGui::EndTable();
			}
		}

		if (ImGui::CollapsingHeader("Resolution")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);

				PropertyRow("Enabled");
				ImGui::Checkbox("Enabled", &p.resolution_enabled);

				PropertyRow("Width");
				ImGui::InputInt("##width", &p.width);

				PropertyRow("Height");
				ImGui::InputInt("##height", &p.height);

				ImGui::EndTable();
			}
		}

		if (ImGui::CollapsingHeader("DPI")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);

				PropertyRow("Enabled");
				ImGui::Checkbox("Enabled", &p.dpi_enabled);

				PropertyRow("DPI");
				ImGui::InputInt("##dpi", &p.dpi);

				PropertyRow("Handling");
				for (int i = 0; i < std::size(DpiOpNames); i++) {
					if (ImGui::RadioButton(DpiOpNames[i].data(), p.dpi_op == i)) {
						p.dpi_op = static_cast<DpiOp>(i);
					}
					ImGui::SameLine();
				}
				ImGui::NewLine();


				ImGui::EndTable();
			}
		}

		if (ImGui::CollapsingHeader("Write")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthStretch);

				PropertyRow("Exports");
				if (ImGui::BeginListBox("##formats")) {
					for (int i = 0; i < p.formats.size(); i++) {
						ImageFormat format = p.formats[i];
						ImGui::TextUnformatted(ImageFormatNames[format].data());
						ImGui::SameLine();
						if (ImGui::Button(std::format("X##{}", i).data())) {
							p.formats.erase(p.formats.begin() + i);
						}
					}

					ImGui::EndListBox();
				}


				PropertyRow("Export Format");
				if (ImGui::BeginCombo("##add_format", ImageFormatNames[s.selected_format].data())) {
					for (int i = 0; i < std::size(ImageFormatNames); i++) {
						bool is_selected = i == s.selected_format;
						if (ImGui::Selectable(ImageFormatNames[i].data(), is_selected)) {
							s.selected_format = static_cast<ImageFormat>(i);
						}
						if (is_selected) ImGui::SetItemDefaultFocus();
					}

					ImGui::EndCombo();
				}

				if (ImGui::Button("Add")) {
					p.formats.push_back(s.selected_format);
				}


				ImGui::EndTable();
			}
		}

		ImGui::EndChild();
		ImGui::NextColumn();

		ImGui::BeginChild("right");
		ImGui::TextUnformatted("right");
		ImGui::EndChild();
	}
	ImGui::Columns(1);
	ImGui::EndChild();

	ImGui::Separator();
	ImGui::AlignTextToFramePadding();
	ImGui::Text("%zu export format(s)", p.formats.size());

	const char *right_text = "Ready";
	float right_w = ImGui::CalcTextSize(right_text).x;
	ImGui::SameLine(ImGui::GetContentRegionMax().x - right_w);
	ImGui::TextUnformatted(right_text);


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

	window = glfwCreateWindow(1280, 800, "glfw window", nullptr, nullptr);
	if (!window) {
		std::println("failed ot create GLFW window");
		glfwTerminate();
		return -1;
	}

	glfwMakeContextCurrent(window);
	glfwSetFramebufferSizeCallback(window, framebuffer_size_callback);
	glfwSetWindowUserPointer(window, this);
	glfwSetWindowRefreshCallback(window, [](GLFWwindow *window) {
		auto *app = static_cast<Ui *>(glfwGetWindowUserPointer(window));
		app->render_frame();
	});
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

	ui(profile, state);

	ImGui::ShowDemoWindow(nullptr);

	ImGui::Render();
	ImGui_ImplOpenGL3_RenderDrawData(ImGui::GetDrawData());

	if (ImGui::GetIO().ConfigFlags & ImGuiConfigFlags_ViewportsEnable) {
		GLFWwindow *backup = glfwGetCurrentContext();
		ImGui::UpdatePlatformWindows();
		ImGui::RenderPlatformWindowsDefault();
		glfwMakeContextCurrent(backup);
	}

	glfwSwapBuffers(window);
}
