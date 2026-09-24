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

	std::vector<ImageFormat> formats;
};

inline constexpr std::string_view MIGRATIONS[] = {
	R"sql(
        CREATE TABLE export_profile (
            id                    INTEGER PRIMARY KEY,
            name                  TEXT    NOT NULL,

            color_space_enabled   BOOLEAN NOT NULL,
            color_space           INTEGER NOT NULL,
            color_space_op        INTEGER NOT NULL,
            color_space_embedd    BOOLEAN NOT NULL,

            bit_depth_enabled     BOOLEAN NOT NULL,
            bit_depth             INTEGER NOT NULL,
            keep_alpha            BOOLEAN NOT NULL,

            resolution_enabled    BOOLEAN NOT NULL,
            width                 INTEGER NOT NULL,
            height                INTEGER NOT NULL,

            dpi_enabled           BOOLEAN NOT NULL,
            dpi                   INTEGER NOT NULL,
            dpi_op                INTEGER NOT NULL
        );

        CREATE TABLE export_format (
            profile_id  INTEGER NOT NULL REFERENCES export_profile(id) ON DELETE CASCADE,
            format      INTEGER NOT NULL,
			PRIMARY KEY (profile_id, format)
        );
    )sql"
};

class Store {
	Database &db;

	void migrate() const;

public:
	explicit Store(Database &db);

	// Returns the new profile's id, or 0 on failure.
	int create_profile(const ExportProfile &p) const;
	bool update_profile(const ExportProfile &p) const;
	[[nodiscard]] std::vector<ExportProfile> get_profiles() const;
	bool delete_profile(const ExportProfile &profile) const;
};
