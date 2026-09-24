#include "img.h"

#include <algorithm>
#include <cmath>
#include <format>
#include <memory>
#include <print>
#include <vips/vips.h>

namespace img {
	using Image = std::unique_ptr<VipsImage, decltype([](VipsImage *img) { g_object_unref(img); })>;

	constexpr double MM_PER_INCH = 25.4;
	// libvips reports 1 pixel/mm when a file carries no resolution.
	constexpr double UNTAGGED_DPI = 72.0;
	constexpr int JPEG_QUALITY = 92;

	// Indexed by ColorSpace. Both are built into libvips.
	constexpr const char *PROFILES[] = {"srgb", "cmyk"};
	// Indexed by BitDepth.
	constexpr VipsBandFormat DEPTH_FORMATS[] = {VIPS_FORMAT_UCHAR, VIPS_FORMAT_USHORT, VIPS_FORMAT_FLOAT};
	constexpr double DEPTH_MAX[] = {255.0, 65535.0, 1.0};
	// Indexed by ImageFormat.
	constexpr const char *EXTENSIONS[] = {".jpg", ".png", ".tif"};

	static std::string take_error() {
		std::string msg = vips_error_buffer();
		vips_error_clear();
		while (!msg.empty() && msg.back() == '\n') msg.pop_back();
		return msg;
	}

	// Replaces img with the result of a libvips operation taking (in, &out, args..., NULL).
	// On failure img is untouched and the reason is left in the vips error buffer.
	template<typename Op, typename... Args>
	static bool apply(Image &img, Op op, Args... args) {
		VipsImage *out = nullptr;
		if (op(img.get(), &out, args..., nullptr)) return false;
		img.reset(out);
		return true;
	}

	// The value of a fully saturated channel (and of opaque alpha) for the image's sample format.
	static double format_max(VipsImage *img) {
		switch (vips_image_get_format(img)) {
			case VIPS_FORMAT_UCHAR:
			case VIPS_FORMAT_CHAR:
				return 255.0;
			case VIPS_FORMAT_FLOAT:
			case VIPS_FORMAT_DOUBLE:
				return 1.0;
			default:
				return 65535.0;
		}
	}

	static int color_bands(VipsImage *img) {
		return vips_image_get_bands(img) - (vips_image_hasalpha(img) ? 1 : 0);
	}

	static bool is_deep(VipsImage *img) {
		const VipsBandFormat format = vips_image_get_format(img);
		return format != VIPS_FORMAT_UCHAR && format != VIPS_FORMAT_CHAR;
	}

	static VipsInterpretation depth_interpretation(VipsImage *img, BitDepth depth) {
		if (vips_image_get_interpretation(img) == VIPS_INTERPRETATION_CMYK) return VIPS_INTERPRETATION_CMYK;
		if (color_bands(img) < 3) return depth == BPC_16 ? VIPS_INTERPRETATION_GREY16 : VIPS_INTERPRETATION_B_W;
		return depth == BPC_16 ? VIPS_INTERPRETATION_RGB16 : VIPS_INTERPRETATION_sRGB;
	}

	// Rescales samples to the full range of the target depth. 32-bit float uses 0..1.
	static bool to_depth(Image &img, BitDepth depth) {
		// scRGB is linear light, so a plain rescale would lose the sRGB transfer curve.
		if (vips_image_get_interpretation(img.get()) == VIPS_INTERPRETATION_scRGB && depth != BPC_32 &&
		    !apply(img, vips_colourspace, VIPS_INTERPRETATION_RGB16))
			return false;

		if (vips_image_get_format(img.get()) == DEPTH_FORMATS[depth]) return true;

		// The 0.5 offset turns the truncating cast into round-to-nearest. vips_cast clips out of range values.
		const double offset = depth == BPC_32 ? 0.0 : 0.5;
		return apply(img, vips_linear1, DEPTH_MAX[depth] / format_max(img.get()), offset) &&
		       apply(img, vips_cast, DEPTH_FORMATS[depth]) &&
		       apply(img, vips_copy, "interpretation", depth_interpretation(img.get(), depth));
	}

	// Composites the image onto white paper and removes the alpha channel.
	static bool drop_alpha(Image &img) {
		if (!vips_image_hasalpha(img.get())) return true;

		const VipsBandFormat format = vips_image_get_format(img.get());
		const double max = format_max(img.get());
		// White is no ink in CMYK.
		const double white = vips_image_get_interpretation(img.get()) == VIPS_INTERPRETATION_CMYK ? 0.0 : max;

		VipsArrayDouble *background = vips_array_double_newv(1, white);
		const bool ok = apply(img, vips_flatten, "background", background, "max_alpha", max) &&
		                apply(img, vips_cast, format);
		vips_area_unref(VIPS_AREA(background));
		return ok;
	}

	static bool resize(Image &img, double hscale, double vscale) {
		if (hscale == 1.0 && vscale == 1.0) return true;

		if (!vips_image_hasalpha(img.get())) {
			return apply(img, vips_resize, hscale, "vscale", vscale);
		}

		// Premultiply so fully transparent pixels don't bleed their color into the edges.
		const VipsBandFormat format = vips_image_get_format(img.get());
		const double max = format_max(img.get());
		return apply(img, vips_premultiply, "max_alpha", max) &&
		       apply(img, vips_resize, hscale, "vscale", vscale) &&
		       apply(img, vips_unpremultiply, "max_alpha", max) &&
		       apply(img, vips_cast, format);
	}

	// Tags the pixels with a profile without changing them. The channel count has to match the profile.
	static bool assign_profile(Image &img, ColorSpace space) {
		const int expected = space == COLOR_CMYK ? 4 : 3;
		if (const int bands = color_bands(img.get()); bands != expected) {
			vips_error("luma", "cannot assign a %s profile to an image with %d color channels",
			           ColorSpaceNames[space].data(), bands);
			return false;
		}

		VipsBlob *profile = nullptr;
		if (vips_profile_load(PROFILES[space], &profile, nullptr)) return false;

		const VipsInterpretation interpretation = space == COLOR_CMYK
			                                          ? VIPS_INTERPRETATION_CMYK
			                                          : is_deep(img.get())
				                                          ? VIPS_INTERPRETATION_RGB16
				                                          : VIPS_INTERPRETATION_sRGB;

		// Copy first: the input may be shared through the operation cache, so its metadata must not change.
		const bool ok = apply(img, vips_copy, "interpretation", interpretation);
		if (ok) {
			size_t length = 0;
			const void *data = vips_blob_get(profile, &length);
			vips_image_set_blob_copy(img.get(), VIPS_META_ICC_NAME, data, length);
		}

		vips_area_unref(VIPS_AREA(profile));
		return ok;
	}

	static bool color_stage(Image &img, const ExportProfile &p) {
		if (p.color_space_op == COLOR_OP_CONVERT) {
			const bool deep = is_deep(img.get());

			// Untagged greyscale has no default input profile, so promote it to RGB first.
			if (color_bands(img.get()) < 3 && !vips_image_get_typeof(img.get(), VIPS_META_ICC_NAME) &&
			    !apply(img, vips_colourspace, deep ? VIPS_INTERPRETATION_RGB16 : VIPS_INTERPRETATION_sRGB))
				return false;

			// Uses the embedded profile as the source, falling back to sRGB or CMYK based on the channel count.
			if (!apply(img, vips_icc_transform, PROFILES[p.color_space], "embedded", TRUE, "depth", deep ? 16 : 8))
				return false;
		} else if (!assign_profile(img, p.color_space)) {
			return false;
		}

		if (!p.embedd) {
			if (!apply(img, vips_copy)) return false;
			vips_image_remove(img.get(), VIPS_META_ICC_NAME);
		}

		return true;
	}

	static bool bit_depth_stage(Image &img, const ExportProfile &p) {
		return (p.keep_alpha || drop_alpha(img)) && to_depth(img, p.bit_depth);
	}

	// Fits the image inside width x height, keeping the aspect ratio. A side <= 0 is unconstrained.
	static bool resolution_stage(Image &img, const ExportProfile &p) {
		const double width = vips_image_get_width(img.get());
		const double height = vips_image_get_height(img.get());
		const double sx = p.width > 0 ? p.width / width : 0.0;
		const double sy = p.height > 0 ? p.height / height : 0.0;

		if (sx == 0.0 && sy == 0.0) {
			vips_error("luma", "resolution needs a width or a height");
			return false;
		}

		const double scale = sx > 0.0 && sy > 0.0 ? std::min(sx, sy) : std::max(sx, sy);

		// Scale each axis to a whole pixel count so the constraining side lands exactly on the target.
		const double target_w = std::max(1.0, std::round(width * scale));
		const double target_h = std::max(1.0, std::round(height * scale));
		return resize(img, target_w / width, target_h / height);
	}

	static double source_dpi(double pixels_per_mm) {
		return pixels_per_mm > 1.0 ? pixels_per_mm * MM_PER_INCH : UNTAGGED_DPI;
	}

	static bool dpi_stage(Image &img, const ExportProfile &p) {
		if (p.dpi <= 0) {
			vips_error("luma", "invalid DPI %d", p.dpi);
			return false;
		}

		// Resampling keeps the print size: the pixel count changes by new DPI / old DPI.
		if (p.dpi_op == DPI_RESAMPLE &&
		    !resize(img, p.dpi / source_dpi(vips_image_get_xres(img.get())),
		            p.dpi / source_dpi(vips_image_get_yres(img.get()))))
			return false;

		const double pixels_per_mm = p.dpi / MM_PER_INCH;
		return apply(img, vips_copy, "xres", pixels_per_mm, "yres", pixels_per_mm);
	}

	// Adapts the image to what the format can hold, then writes it.
	static bool save(const Image &processed, ImageFormat format, const std::string &path) {
		g_object_ref(processed.get());
		Image img{processed.get()};

		switch (format) {
			case IMAGE_JPEG:
				return drop_alpha(img) && to_depth(img, BPC_8) &&
				       !vips_jpegsave(img.get(), path.c_str(), "Q", JPEG_QUALITY, nullptr);

			case IMAGE_PNG:
				if (vips_image_get_interpretation(img.get()) == VIPS_INTERPRETATION_CMYK) {
					vips_error("luma", "PNG cannot store CMYK");
					return false;
				}
				if (vips_image_get_format(img.get()) != VIPS_FORMAT_UCHAR &&
				    vips_image_get_format(img.get()) != VIPS_FORMAT_USHORT && !to_depth(img, BPC_16))
					return false;
				return !vips_pngsave(img.get(), path.c_str(), nullptr);

			case IMAGE_TIFF:
				return !vips_tiffsave(img.get(), path.c_str(),
				                      "compression", VIPS_FOREIGN_TIFF_COMPRESSION_LZW, nullptr);
		}

		vips_error("luma", "unknown export format %d", format);
		return false;
	}

	static void export_file(const ExportProfile &p, const fs::path &output_dir, ExportResult &result) {
		Image img{vips_image_new_from_file(utf8(result.source).c_str(), nullptr)};

		const bool ok = img && apply(img, vips_autorot) &&
		                (!p.color_space_enabled || color_stage(img, p)) &&
		                (!p.bit_depth_enabled || bit_depth_stage(img, p)) &&
		                (!p.resolution_enabled || resolution_stage(img, p)) &&
		                (!p.dpi_enabled || dpi_stage(img, p));
		if (!ok) {
			result.error = take_error();
			return;
		}

		// libvips is lazy: without this, every format would decode and process the source again.
		if (p.formats.size() > 1) {
			VipsImage *rendered = vips_image_copy_memory(img.get());
			if (!rendered) {
				result.error = take_error();
				return;
			}
			img.reset(rendered);
		}

		for (const ImageFormat format: p.formats) {
			fs::path out = output_dir / result.source.stem();
			out += EXTENSIONS[format];

			if (std::error_code ec; fs::equivalent(result.source, out, ec)) {
				result.error = std::format("{} would overwrite the source file", ImageFormatNames[format]);
				return;
			}

			if (!save(img, format, utf8(out))) {
				result.error = std::format("{}: {}", ImageFormatNames[format], take_error());
				return;
			}

			result.outputs.push_back(std::move(out));
		}
	}

	bool init() {
		if (VIPS_INIT("luma")) {
			std::println("failed to start libvips: {}", take_error());
			return false;
		}

		// Each file is processed once, so caching only holds memory and keeps source files open.
		vips_cache_set_max(0);
		return true;
	}

	void shutdown() {
		vips_shutdown();
	}

	std::vector<ExportResult> execute_profile(const std::vector<fs::path> &files, const ExportProfile &profile,
	                                          const fs::path &output_dir, const Progress &progress) {
		std::vector<ExportResult> results;
		results.reserve(files.size());

		std::error_code ec;
		fs::create_directories(output_dir, ec);

		for (const auto &file: files) {
			auto &result = results.emplace_back(file);

			if (ec) {
				result.error = std::format("cannot create {}: {}", utf8(output_dir), ec.message());
			} else if (profile.formats.empty()) {
				result.error = "profile has no export formats";
			} else {
				export_file(profile, output_dir, result);
			}

			if (result.error.empty()) {
				std::println("exported {}", utf8(file));
			} else {
				std::println("failed to export {}: {}", utf8(file), result.error);
			}

			if (progress && !progress(result)) break;
		}

		return results;
	}
}
