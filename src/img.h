#pragma once

#include <functional>
#include <string>
#include <vector>
#include "store.h"

namespace img {
	struct ExportResult {
		fs::path source;
		std::vector<fs::path> outputs;
		// Empty on success. Formats written before a failure are still listed in outputs.
		std::string error;
	};

	// std::filesystem uses the ANSI code page for narrow strings on Windows; libvips, GLFW and ImGui use UTF-8.
	inline std::string utf8(const fs::path &path) {
		const auto s = path.u8string();
		return {reinterpret_cast<const char *>(s.data()), s.size()};
	}

	inline fs::path path_from_utf8(const std::string &s) {
		return {std::u8string(reinterpret_cast<const char8_t *>(s.data()), s.size())};
	}

	// Starts libvips. Call once before execute_profile().
	bool init();
	void shutdown();

	// Called after each file. Returning false stops the batch.
	using Progress = std::function<bool(const ExportResult &)>;

	// Runs every file through the profile's enabled stages (color, bit depth, resolution, DPI) in that order,
	// then writes one file per export format to output_dir as <stem>.<ext>.
	// Blocks until done, so call it off the UI thread.
	std::vector<ExportResult> execute_profile(const std::vector<fs::path> &files, const ExportProfile &profile,
	                                          const fs::path &output_dir, const Progress &progress = {});
}
