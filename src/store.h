#pragma once

#include <filesystem>
#include <vector>
#include "db.h"

namespace fs = std::filesystem;

enum ColorSpace {
	COLOR_SRGB,
	COLOR_CMYK,
};

enum ImageFormat {
	IMAGE_JPEG,
	IMAGE_PNG,
	IMAGE_TIFF,
};

struct ExportProfile {
	int id;
	std::string name;
	int width;
	int height;
	ColorSpace color_space;
	int dpi;
	int bit_depth;
	ImageFormat format;
};

class Store {
	Database &db;

public:
	explicit Store(Database &db) : db(db) {
	};

	void create_profile(const ExportProfile &p) const;
	[[nodiscard]] std::vector<ExportProfile> get_profiles() const;
	void delete_profile(ExportProfile &profile) const;
};
