#include "store.h"
#include <print>

void Store::create_profile(const ExportProfile &p) const {
	auto conn = db.connection();
	auto q = conn.query("INSERT INTO export_profile (name, width, height, color_space, dpi, bit_depth, format)"
		"VALUES (?,?,?,?,?,?,?);");

	q.bind(p.name.c_str());
	q.bind(p.width);
	q.bind(p.height);
	q.bind(p.color_space);
	q.bind(p.dpi);
	q.bind(p.bit_depth);
	q.bind(p.format);

	if (!q.exec()) {
		std::println("failed to create profile {}", db.error());
	}
}

std::vector<ExportProfile> Store::get_profiles() const {
	std::vector<ExportProfile> data;

	auto conn = db.connection();
	auto q = conn.query("SELECT * FROM export_profile;");

	while (q.next_step()) {
		data.emplace_back(
			q.get_column<int>(0),
			q.get_column<std::string>(1),
			q.get_column<int>(2),
			q.get_column<int>(3),
			static_cast<ColorSpace>(q.get_column<int>(4)),
			q.get_column<int>(5),
			q.get_column<int>(6),
			static_cast<ImageFormat>(q.get_column<int>(7))
		);
	}

	return data;
}

void Store::delete_profile(ExportProfile &profile) const {
	auto conn = db.connection();

	auto q = conn.query("DELETE * FROM export_profiles WHERE id = ?;");
	q.bind(profile.id);

	if (!q.exec()) {
		std::println("failed to delete profile {}", profile.id);
	}
}
