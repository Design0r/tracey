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

inline constexpr std::array<std::string_view, 1> MIGRATIONS = {
	"CREATE TABLE IF NOT EXISTS export_profile ("
	"id          INTEGER     PRIMARY KEY AUTOINCREMENT,"
	"name        TEXT		 NOT NULL,"
	"width       INTEGER     NOT NULL,"
	"height      INTEGER     NOT NULL,"
	"color_space TEXT	     NOT NULL,"
	"dpi         INTEGER     NOT NULL,"
	"bit_depth   INTEGER     NOT NULL,"
	"format      TEXT	     NOT NULL"
	");",
};

class Store {
	Database &db;

private:
	void migrate() const;

public:
	explicit Store(Database &db);

	void create_profile(const ExportProfile &p) const;
	[[nodiscard]] std::vector<ExportProfile> get_profiles() const;
	void delete_profile(ExportProfile &profile) const;
};
