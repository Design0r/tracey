#pragma once
#include <atomic>
#include <mutex>
#include <string>
#include <thread>
#include "img.h"
#include "store.h"

#define GLFW_INCLUDE_NONE
#include <GLFW/glfw3.h>

// An export running on a worker thread. results[i] belongs to sources[i] of the batch's snapshot,
// which is why the source list can only grow while it runs.
struct Batch {
	std::jthread worker;
	std::mutex mutex;
	std::vector<img::ExportResult> results;
	std::atomic<bool> running = false;
	size_t total = 0;
};

struct UiState {
	std::vector<ExportProfile> profiles;
	// Edits apply to this copy until the profile is saved.
	ExportProfile selected_profile{};
	ImageFormat selected_format = IMAGE_JPEG;

	std::vector<fs::path> sources;
	std::string output_dir;

	// Shown in the status bar after a profile action.
	std::string message;
	Batch batch;
};

class Ui {
	GLFWwindow *window = nullptr;
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
