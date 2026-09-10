#pragma once

#include <filesystem>
#include <vector>
#include "db.h"

namespace fs = std::filesystem;

enum ColorSpace {
	COLOR_SRGB,
	COLOR_CMYK,
};

constexpr std::string_view ColorSpaceNames[] = {"sRGB", "CMYK"};

enum ColorSpaceOp {
	COLOR_OP_CONVERT,
	COLOR_OP_ASSIGN,
};

constexpr std::string_view ColorSpaceOpNames[] = {"Convert", "Assign"};

enum ImageFormat {
	IMAGE_JPEG,
	IMAGE_PNG,
	IMAGE_TIFF,
};

constexpr std::string_view ImageFormatNames[] = {"JPEG", "PNG", "TIFF"};

enum BitDepth {
	BPC_8,
	BPC_16,
	BPC_32,
};

constexpr std::string_view BitDepthNames[] = {"8-Bit", "16-Bit", "32-Bit Float"};

enum DpiOp {
	DPI_TAG_ONLY,
	DPI_RESAMPLE,
};

constexpr std::string_view DpiOpNames[] = {"Tag Only", "Resample"};

struct ExportProfile {
	int id;
	std::string name;

	bool color_space_enabled;
	ColorSpace color_space;
	ColorSpaceOp color_space_op;
	bool embedd;

	bool bit_depth_enabled;
	BitDepth bit_depth;
	bool keep_alpha;

	bool resolution_enabled;
	int width;
	int height;

	bool dpi_enabled;
	int dpi;
	DpiOp dpi_op;

	ImageFormat format;
};

inline constexpr std::array<std::string_view, 1> MIGRATIONS = {
	"CREATE TABLE IF NOT EXISTS export_profile ("
	"id						INTEGER     PRIMARY KEY AUTOINCREMENT,"
	"name					TEXT		NOT NULL,"

	"color_space_enabled	BOOLEAN		NOT NULL,"
	"color_space			INTEGER     NOT NULL,"
	"color_space_op			INTEGER     NOT NULL,"
	"embedd					BOOLEAN		NOT NULL,"

	"bit_depth_enabled		BOOLEAN		NOT NULL,"
	"bit_depth				INTEGER     NOT NULL,"
	"keep_alpha				BOOLEAN		NOT NULL,"

	"resolution_enabled		BOOLEAN		NOT NULL,"
	"width					INTEGER     NOT NULL,"
	"height					INTEGER     NOT NULL,"

	"dpi_enabled			BOOLEAN		NOT NULL,"
	"dpi					INTEGER     NOT NULL,"
	"dpi_op					INTEGER     NOT NULL,"

	"format					INTEGER     NOT NULL"
	");",
};

class Store {
	Database &db;

	void migrate() const;

public:
	explicit Store(Database &db);

	void create_profile(const ExportProfile &p) const;
	[[nodiscard]] std::vector<ExportProfile> get_profiles() const;
	void delete_profile(ExportProfile &profile) const;
};
