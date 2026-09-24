#include "ui.h"
#include "theme.h"

#include <algorithm>
#include <cctype>
#include <format>
#include <imgui.h>
#include <imgui_stdlib.h>
#include <optional>
#include <print>
#include <glad/glad.h>

#include <imgui_impl_glfw.h>
#include <imgui_impl_opengl3.h>

static void framebuffer_size_callback(GLFWwindow *window, int width, int height) {
	glViewport(0, 0, width, height);
}

static ExportProfile new_profile() {
	return {
		.id = 0,
		.name = "New Profile",

		.color_space_enabled = false,
		.color_space = COLOR_SRGB,
		.color_space_op = COLOR_OP_CONVERT,
		.embedd = true,

		.bit_depth_enabled = false,
		.bit_depth = BPC_8,
		.keep_alpha = true,

		.resolution_enabled = false,
		.width = 2048,
		.height = 2048,

		.dpi_enabled = false,
		.dpi = 300,
		.dpi_op = DPI_TAG_ONLY,

		.formats = {IMAGE_JPEG},
	};
}

// Extensions picked up when a folder is dropped. Single files are passed through and libvips decides.
static bool is_image(const fs::path &path) {
	std::string ext = img::utf8(path.extension());
	std::ranges::transform(ext, ext.begin(), [](unsigned char c) { return std::tolower(c); });
	return ext == ".jpg" || ext == ".jpeg" || ext == ".png" || ext == ".tif" || ext == ".tiff";
}

static void add_source(UiState &s, const fs::path &path) {
	if (std::ranges::find(s.sources, path) != s.sources.end()) return;

	if (s.output_dir.empty()) {
		s.output_dir = img::utf8(path.parent_path() / "export");
	}
	s.sources.push_back(path);
}

static void add_dropped(UiState &s, const fs::path &path) {
	std::error_code ec;
	if (!fs::is_directory(path, ec)) {
		add_source(s, path);
		return;
	}

	std::vector<fs::path> files;
	for (const auto &entry: fs::directory_iterator(path, ec)) {
		if (entry.is_regular_file(ec) && is_image(entry.path())) files.push_back(entry.path());
	}
	std::ranges::sort(files);

	for (const auto &file: files) add_source(s, file);
}

static void start_batch(UiState &s) {
	Batch &batch = s.batch;
	batch.results.clear();
	batch.total = s.sources.size();
	batch.running = true;

	batch.worker = std::jthread([&batch, files = s.sources, profile = s.selected_profile,
			output_dir = img::path_from_utf8(s.output_dir)](const std::stop_token &stop) {
			img::execute_profile(files, profile, output_dir, [&](const img::ExportResult &result) {
				std::lock_guard lock(batch.mutex);
				batch.results.push_back(result);
				return !stop.stop_requested();
			});
			batch.running = false;
		});
}

namespace ui {
	static const ImVec4 COLOR_ERROR{0.92f, 0.40f, 0.40f, 1.0f};

	static void label(const char *label) {
		ImGui::TableNextRow();
		ImGui::TableSetColumnIndex(0);
		ImGui::AlignTextToFramePadding();
		ImGui::TextUnformatted(label);
		ImGui::TableSetColumnIndex(1);
		ImGui::SetNextItemWidth(-FLT_MIN);
	}

	static void reload_profiles(Store &store, UiState &s, int select_id) {
		s.profiles = store.get_profiles();

		const auto it = std::ranges::find(s.profiles, select_id, &ExportProfile::id);
		if (it != s.profiles.end()) {
			s.selected_profile = *it;
		} else {
			s.selected_profile = s.profiles.empty() ? new_profile() : s.profiles.front();
		}
	}

	static void save_profile(Store &store, UiState &s) {
		ExportProfile &p = s.selected_profile;
		if (p.name.empty()) {
			s.message = "Name the profile before saving";
			return;
		}

		if (p.id == 0) {
			const int id = store.create_profile(p);
			if (id == 0) {
				s.message = "Failed to save profile";
				return;
			}
			p.id = id;
		} else if (!store.update_profile(p)) {
			s.message = "Failed to save profile";
			return;
		}

		s.message = std::format("Saved \"{}\"", p.name);
		reload_profiles(store, s, p.id);
	}

	static void delete_profile(Store &store, UiState &s) {
		const ExportProfile p = s.selected_profile;
		if (p.id != 0 && !store.delete_profile(p)) {
			s.message = "Failed to delete profile";
			return;
		}

		s.message = std::format("Deleted \"{}\"", p.name);
		reload_profiles(store, s, 0);
	}

	static void header(Store &store, UiState &s) {
		ExportProfile &selected_profile = s.selected_profile;

		if (ImGui::Button("New Profile")) {
			selected_profile = new_profile();
			s.message.clear();
		}

		ImGui::SameLine();
		if (ImGui::Button("Save Profile")) {
			save_profile(store, s);
		}

		ImGui::SameLine();
		if (ImGui::Button("Delete Profile")) {
			delete_profile(store, s);
		}

		ImGui::SameLine();
		ImGui::SetNextItemWidth(ImGui::GetFontSize() * 12.0f);
		const char *preview = selected_profile.id == 0 ? "Unsaved profile" : selected_profile.name.c_str();
		if (ImGui::BeginCombo("##profile_select", preview)) {
			for (const auto &profile: s.profiles) {
				bool is_selected = profile.id == selected_profile.id;
				if (ImGui::Selectable(profile.name.data(), is_selected)) {
					selected_profile = profile;
					s.message.clear();
				}
				if (is_selected) ImGui::SetItemDefaultFocus();
			}

			ImGui::EndCombo();
		}

		ImGui::SameLine();
		ImGui::SetNextItemWidth(ImGui::GetFontSize() * 12.0f);
		ImGui::InputTextWithHint("##profile_name", "Profile name", &selected_profile.name);

		ImGui::SameLine();
		const bool can_run = !s.batch.running && !s.sources.empty() && !selected_profile.formats.empty() &&
		                     !s.output_dir.empty();
		ImGui::BeginDisabled(!can_run);
		if (ImGui::Button("Run Batch")) {
			start_batch(s);
		}
		ImGui::EndDisabled();
		if (!can_run && !s.batch.running && ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled)) {
			ImGui::SetTooltip("Add source files, an export format and an output folder first");
		}

		ImGui::Separator();
	}

	static void sources(UiState &s) {
		ImGui::TextUnformatted("Files");

		const bool running = s.batch.running;
		ImGui::SameLine();
		ImGui::BeginDisabled(running || s.sources.empty());
		if (ImGui::SmallButton("Clear")) {
			s.sources.clear();
			s.batch.results.clear();
		}
		ImGui::EndDisabled();

		ImGui::Separator();

		if (s.sources.empty()) {
			ImGui::TextDisabled("Drop images or folders onto the window.");
			return;
		}

		std::lock_guard lock(s.batch.mutex);
		const auto &results = s.batch.results;

		std::optional<size_t> remove;
		for (size_t i = 0; i < s.sources.size(); i++) {
			ImGui::PushID(static_cast<int>(i));

			ImGui::BeginDisabled(running);
			if (ImGui::SmallButton("X")) remove = i;
			ImGui::EndDisabled();

			ImGui::SameLine();
			ImGui::TextUnformatted(img::utf8(s.sources[i].filename()).c_str());
			if (ImGui::IsItemHovered()) ImGui::SetTooltip("%s", img::utf8(s.sources[i]).c_str());

			if (i < results.size()) {
				ImGui::SameLine();
				if (results[i].error.empty()) {
					ImGui::TextDisabled("done");
				} else {
					ImGui::TextColored(COLOR_ERROR, "failed");
					if (ImGui::IsItemHovered()) ImGui::SetTooltip("%s", results[i].error.c_str());
				}
			}

			ImGui::PopID();
		}

		if (remove) {
			s.sources.erase(s.sources.begin() + *remove);
			if (*remove < s.batch.results.size()) s.batch.results.erase(s.batch.results.begin() + *remove);
		}
	}

	static void body(UiState &s) {
		ExportProfile &selected_profile = s.selected_profile;
		const ImGuiStyle &style = ImGui::GetStyle();
		const float status_h = ImGui::GetFrameHeight() + style.ItemSpacing.y * 2.0f + 1.0f;

		ImGui::BeginChild("##body", ImVec2(0, -status_h));
		if (!ImGui::BeginTable("##layout", 2, ImGuiTableFlags_BordersInnerV | ImGuiTableFlags_Resizable,
		                       ImVec2(0, -FLT_MIN))) {
			ImGui::EndChild();
			return;
		}
		ImGui::TableSetupColumn("left", ImGuiTableColumnFlags_WidthStretch, 1.0f);
		ImGui::TableSetupColumn("center", ImGuiTableColumnFlags_WidthStretch, 2.0f);
		ImGui::TableNextColumn();

		ImGui::BeginChild("left");
		sources(s);
		ImGui::EndChild();

		ImGui::TableNextColumn();

		ImGui::BeginChild("center");
		ImGui::TextUnformatted("Pipeline");
		ImGui::TextUnformatted(
			"Every file in the batch runs through these stages in order. The line tracks what each stage leaves behind.");

		ImGui::PushID("color");
		if (ImGui::CollapsingHeader("Color")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);

				label("Enabled");
				ImGui::Checkbox("Enabled", &selected_profile.color_space_enabled);

				label("Color Profile");
				if (ImGui::BeginCombo("##ColorProfile", ColorSpaceNames[selected_profile.color_space].data())) {
					for (int i = 0; i < std::size(ColorSpaceNames); i++) {
						bool is_selected = selected_profile.color_space == i;
						if (ImGui::Selectable(ColorSpaceNames[i].data(), is_selected)) {
							selected_profile.color_space = static_cast<ColorSpace>(i);
						}

						if (is_selected) ImGui::SetItemDefaultFocus();
					}

					ImGui::EndCombo();
				}


				label("Handling");
				for (int i = 0; i < std::size(ColorSpaceOpNames); i++) {
					if (ImGui::RadioButton(ColorSpaceOpNames[i].data(), selected_profile.color_space_op == i)) {
						selected_profile.color_space_op = static_cast<ColorSpaceOp>(i);
					}
					ImGui::SameLine();
				}
				ImGui::NewLine();

				label("Embed");
				ImGui::Checkbox("Embed ICC Profile", &selected_profile.embedd);

				ImGui::EndTable();
			}
		}
		ImGui::PopID();

		ImGui::PushID("bit_depth");
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
				ImGui::Checkbox("Keep Alpha Channel", &selected_profile.keep_alpha);

				ImGui::EndTable();
			}
		}
		ImGui::PopID();

		ImGui::PushID("resolution");
		if (ImGui::CollapsingHeader("Resolution")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);

				label("Enabled");
				ImGui::Checkbox("Enabled", &selected_profile.resolution_enabled);

				label("Width");
				if (ImGui::InputInt("##width", &selected_profile.width)) {
					selected_profile.width = std::max(0, selected_profile.width);
				}

				label("Height");
				if (ImGui::InputInt("##height", &selected_profile.height)) {
					selected_profile.height = std::max(0, selected_profile.height);
				}

				ImGui::TableNextRow();
				ImGui::TableSetColumnIndex(1);
				ImGui::TextDisabled("Fits inside the box, keeping the aspect ratio. 0 leaves a side unconstrained.");

				ImGui::EndTable();
			}
		}
		ImGui::PopID();

		ImGui::PushID("dpi");
		if (ImGui::CollapsingHeader("DPI")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);

				label("Enabled");
				ImGui::Checkbox("Enabled", &selected_profile.dpi_enabled);

				label("DPI");
				if (ImGui::InputInt("##dpi", &selected_profile.dpi)) {
					selected_profile.dpi = std::max(1, selected_profile.dpi);
				}

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
		ImGui::PopID();

		ImGui::PushID("write");
		if (ImGui::CollapsingHeader("Write")) {
			if (ImGui::BeginTable("##props", 2, ImGuiTableFlags_SizingFixedFit)) {
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthFixed);
				ImGui::TableSetupColumn("", ImGuiTableColumnFlags_WidthStretch);

				label("Output Folder");
				ImGui::InputTextWithHint("##output_dir", "Folder for the exported files", &s.output_dir);

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

				// Every format of a file writes to <stem>.<ext>, so the same format twice would overwrite itself.
				const bool listed = std::ranges::contains(selected_profile.formats, s.selected_format);
				ImGui::BeginDisabled(listed);
				if (ImGui::Button("Add")) {
					selected_profile.formats.push_back(s.selected_format);
				}
				ImGui::EndDisabled();


				ImGui::EndTable();
			}
		}
		ImGui::PopID();

		ImGui::EndChild();

		ImGui::EndTable();
		ImGui::EndChild();
	}

	static void status(UiState &s) {
		Batch &batch = s.batch;

		ImGui::Separator();
		ImGui::AlignTextToFramePadding();
		if (s.message.empty()) {
			ImGui::Text("%zu export format(s)", s.selected_profile.formats.size());
		} else {
			ImGui::TextUnformatted(s.message.c_str());
		}

		size_t done, failed;
		{
			std::lock_guard lock(batch.mutex);
			done = batch.results.size();
			failed = std::ranges::count_if(batch.results, [](const auto &r) { return !r.error.empty(); });
		}

		if (batch.running) {
			const std::string progress = std::format("Exporting {}/{}", done, batch.total);
			const float bar_w = ImGui::GetFontSize() * 10.0f;
			const float cancel_w = ImGui::CalcTextSize("Cancel").x + ImGui::GetStyle().FramePadding.x * 2.0f;
			const float spacing = ImGui::GetStyle().ItemSpacing.x;

			ImGui::SameLine(ImGui::GetContentRegionMax().x - bar_w - cancel_w - spacing);
			ImGui::ProgressBar(batch.total ? static_cast<float>(done) / batch.total : 0.0f, ImVec2(bar_w, 0),
			                   progress.c_str());
			ImGui::SameLine();
			ImGui::BeginDisabled(batch.worker.get_stop_token().stop_requested());
			if (ImGui::Button("Cancel")) batch.worker.request_stop();
			ImGui::EndDisabled();
			return;
		}

		std::string right_text = "Ready";
		if (done > 0) {
			right_text = failed
				             ? std::format("{} exported, {} failed", done - failed, failed)
				             : std::format("{} exported", done);
		}

		float right_w = ImGui::CalcTextSize(right_text.c_str()).x;
		ImGui::SameLine(ImGui::GetContentRegionMax().x - right_w);
		if (failed) {
			ImGui::TextColored(COLOR_ERROR, "%s", right_text.c_str());
		} else {
			ImGui::TextUnformatted(right_text.c_str());
		}
	}

	static void viewport(Store &store, UiState &s) {
		ImGuiViewport *vp = ImGui::GetMainViewport();
		ImGui::SetNextWindowPos(vp->WorkPos);
		ImGui::SetNextWindowSize(vp->WorkSize);
		ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
		ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
		ImGui::Begin("##root", nullptr,
		             ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
		             ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoBringToFrontOnFocus);
		ImGui::PopStyleVar(2);


		header(store, s);
		body(s);
		status(s);

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

Ui::Ui(Store &s) : store(s) {
	ui::reload_profiles(store, state, 0);
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

	window = glfwCreateWindow(1280, 800, "Luma", nullptr, nullptr);
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
	glfwSetDropCallback(window, [](GLFWwindow *window, int count, const char **paths) {
		auto *app = static_cast<Ui *>(glfwGetWindowUserPointer(window));
		for (int i = 0; i < count; i++) {
			add_dropped(app->state, img::path_from_utf8(paths[i]));
		}
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

	ui::viewport(store, state);

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
