#include "ui.h"
#include "theme.h"

#include <format>
#include <imgui.h>
#include <print>
#include <glad/glad.h>

#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>

static void framebuffer_size_callback(GLFWwindow *window, int width, int height) {
	glViewport(0, 0, width, height);
}

namespace ui {
	static void label(const char *label) {
		ImGui::TableNextRow();
		ImGui::TableSetColumnIndex(0);
		ImGui::AlignTextToFramePadding();
		ImGui::TextUnformatted(label);
		ImGui::TableSetColumnIndex(1);
		ImGui::SetNextItemWidth(-FLT_MIN);
	}

	static void header(const std::vector<ExportProfile> &profiles, ExportProfile &selected_profile) {
		ImGui::SameLine();
		if (ImGui::Button("New Profile")) {
		}

		ImGui::SameLine();
		if (ImGui::Button("Save Profile")) {
		}

		ImGui::SameLine();
		if (ImGui::BeginCombo("##profile_select", selected_profile.name.data())) {
			for (const auto &profile: profiles) {
				bool is_selected = profile.id == selected_profile.id;
				if (ImGui::Selectable(profile.name.data(), is_selected)) {
					selected_profile = profile;
				}
				if (is_selected) ImGui::SetItemDefaultFocus();
			}

			ImGui::EndCombo();
		}

		ImGui::SameLine();
		if (ImGui::Button("Run Batch")) {
		}
		ImGui::Separator();
	}

	static void body(ExportProfile &selected_profile, UiState &s) {
		const ImGuiStyle &style = ImGui::GetStyle();
		const float status_h = ImGui::GetFrameHeight() + style.ItemSpacing.y * 2.0f + 1.0f;

		ImGui::BeginChild("##body", ImVec2(0, -status_h));
		// Stretch weights 1:2 start the columns at 1/3 and 2/3 of the width. Dragging the divider changes the weights;
		// the resulting ratio is kept when the window is resized and saved to imgui.ini.
		// The -FLT_MIN height makes the table fill the body, so the child windows in its cells can too.
		if (!ImGui::BeginTable("##layout", 2, ImGuiTableFlags_BordersInnerV | ImGuiTableFlags_Resizable,
		                       ImVec2(0, -FLT_MIN))) {
			ImGui::EndChild();
			return;
		}
		ImGui::TableSetupColumn("left", ImGuiTableColumnFlags_WidthStretch, 1.0f);
		ImGui::TableSetupColumn("center", ImGuiTableColumnFlags_WidthStretch, 2.0f);
		ImGui::TableNextColumn();

		ImGui::BeginChild("left");
		ImGui::TextUnformatted("left");
		ImGui::SameLine();
		ImGui::Button("test btn");
		ImGui::EndChild();

		ImGui::TableNextColumn();

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

				label("Enabled");
				ImGui::Checkbox("Enabled", &selected_profile.color_space_enabled);

				label("Color Profile");
				if (ImGui::BeginCombo("##ColorProfile", ImageFormatNames[selected_profile.color_space].data())) {
					for (int i = 0; i < std::size(ImageFormatNames); i++) {
						bool is_selected = selected_profile.color_space == i;
						if (ImGui::Selectable(ImageFormatNames[i].data(), is_selected)) {
							selected_profile.color_space = static_cast<ColorSpace>(i);
							std::println("{}", ImageFormatNames[selected_profile.color_space]);
						}

						if (is_selected) ImGui::SetItemDefaultFocus();
					}

					ImGui::EndCombo();
				}


				label("Handling");
				for (int i = 0; i < std::size(ColorSpaceOpNames); i++) {
					if (ImGui::RadioButton(ColorSpaceOpNames[i].data(), selected_profile.color_space_op == i)) {
						selected_profile.color_space_op = static_cast<ColorSpaceOp>(i);
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


				label("Enabled");
				ImGui::Checkbox("Enabled", &selected_profile.bit_depth_enabled);

				label("Bit Depth");
				for (int i = 0; i < std::size(BitDepthNames); i++) {
					if (ImGui::RadioButton(BitDepthNames[i].data(), selected_profile.bit_depth == i)) {
						selected_profile.bit_depth = static_cast<BitDepth>(i);
					}

					ImGui::SameLine();
				}

				ImGui::NewLine();


				label("Alpha");
				if (ImGui::Checkbox("Keep Alpha Channel", &selected_profile.keep_alpha)) {
					std::println("Keep Alpha Channel: {}", selected_profile.keep_alpha);
				}

				ImGui::EndTable();
			}
		}

		if (ImGui::CollapsingHeader("Resolution")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);

				label("Enabled");
				ImGui::Checkbox("Enabled", &selected_profile.resolution_enabled);

				label("Width");
				ImGui::InputInt("##width", &selected_profile.width);

				label("Height");
				ImGui::InputInt("##height", &selected_profile.height);

				ImGui::EndTable();
			}
		}

		if (ImGui::CollapsingHeader("DPI")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);

				label("Enabled");
				ImGui::Checkbox("Enabled", &selected_profile.dpi_enabled);

				label("DPI");
				ImGui::InputInt("##dpi", &selected_profile.dpi);

				label("Handling");
				for (int i = 0; i < std::size(DpiOpNames); i++) {
					if (ImGui::RadioButton(DpiOpNames[i].data(), selected_profile.dpi_op == i)) {
						selected_profile.dpi_op = static_cast<DpiOp>(i);
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

				label("Exports");
				if (ImGui::BeginListBox("##formats")) {
					for (int i = 0; i < selected_profile.formats.size(); i++) {
						ImageFormat format = selected_profile.formats[i];
						ImGui::TextUnformatted(ImageFormatNames[format].data());
						ImGui::SameLine();
						if (ImGui::Button(std::format("X##{}", i).data())) {
							selected_profile.formats.erase(selected_profile.formats.begin() + i);
						}
					}

					ImGui::EndListBox();
				}


				label("Export Format");
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
					selected_profile.formats.push_back(s.selected_format);
				}


				ImGui::EndTable();
			}
		}

		ImGui::EndChild();

		ImGui::EndTable();
		ImGui::EndChild();
	}

	static void status(const ExportProfile &selected_profile) {
		ImGui::Separator();
		ImGui::AlignTextToFramePadding();
		ImGui::Text("%zu export format(s)", selected_profile.formats.size());

		const char *right_text = "Ready";
		float right_w = ImGui::CalcTextSize(right_text).x;
		ImGui::SameLine(ImGui::GetContentRegionMax().x - right_w);
		ImGui::TextUnformatted(right_text);
	}

	static void viewport(const std::vector<ExportProfile> &profiles, ExportProfile &selected_profile, UiState &s) {
		ImGuiViewport *vp = ImGui::GetMainViewport();
		ImGui::SetNextWindowPos(vp->WorkPos);
		ImGui::SetNextWindowSize(vp->WorkSize);
		ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
		ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
		ImGui::Begin("##root", nullptr,
		             ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
		             ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoBringToFrontOnFocus);
		ImGui::PopStyleVar(2);


		header(profiles, selected_profile);
		body(selected_profile, s);
		status(selected_profile);

		ImGui::End();
	}
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

Ui::Ui(Store &s) : profiles(s.get_profiles()), store(s) {
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
	theme::load_fonts();
	theme::apply();

	// Returns 1.0 on macOS, where Retina is handled by the framebuffer scale instead.
	const float scale = ImGui_ImplGlfw_GetContentScaleForWindow(window);
	ImGuiStyle &style = ImGui::GetStyle();
	style.ScaleAllSizes(scale);
	style.FontScaleDpi = scale;

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

	ui::viewport(profiles, selected_profile, state);

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
