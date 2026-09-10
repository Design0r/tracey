#include "store.h"
#include <print>

static int get_db_migration_version(Connection &conn) {
	auto query = conn.query("PRAGMA user_version;");
	if (!query.next_step()) {
		std::println("failed to fetch migration_version");
		return 0;
	}

	auto migration_version = query.get_column<int>(0);

	return migration_version;
}

Store::Store(Database &db) : db(db) {
	migrate();
};

void Store::migrate() const {
	auto conn = db.connection();

	auto migration_count = MIGRATIONS.size();

	int migration_version = get_db_migration_version(conn);
	if (migration_version == migration_count) {
		std::println("database migrations up to date ({}/{})", migration_version, migration_count);
		return;
	}

	migration_version = migration_version == 0 ? 0 : migration_version - 1;

	for (int i = migration_version; i < migration_count; i++) {
		if (!conn.exec(MIGRATIONS[i].data())) {
			std::println("failed migration {}", i + 1);
			return;
		}

		std::println("migration executed ({}/{})", i + 1, migration_count);
	}


	auto set_version = conn.query(std::format("PRAGMA user_version = {};", migration_count).c_str());
	if (!set_version.exec()) {
		std::println("failed to set db migration version");
	}
}

void Store::create_profile(const ExportProfile &p) const {
	auto conn = db.connection();
	auto q = conn.query(
		"INSERT INTO export_profile ("
		"name, "
		"color_space_enabled, color_space, color_space_op, embedd, "
		"bit_depth_enabled, bit_depth, keep_alpha, "
		"resolution_enabled, width, height, "
		"dpi_enabled, dpi, dpi_op, "
		"format"
		")"
		"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);");

	q.bind(p.name.c_str());
	q.bind(p.color_space_enabled);
	q.bind(p.color_space);
	q.bind(p.color_space_op);
	q.bind(p.embedd);

	q.bind(p.bit_depth_enabled);
	q.bind(p.bit_depth);
	q.bind(p.keep_alpha);

	q.bind(p.resolution_enabled);
	q.bind(p.width);
	q.bind(p.height);

	q.bind(p.dpi_enabled);
	q.bind(p.dpi);
	q.bind(p.dpi_op);

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
			q.get_column<int>(),
			q.get_column<std::string>(),

			q.get_column<bool>(),
			static_cast<ColorSpace>(q.get_column<int>()),
			static_cast<ColorSpaceOp>(q.get_column<int>()),
			q.get_column<bool>(),

			q.get_column<bool>(),
			static_cast<BitDepth>(q.get_column<int>()),
			q.get_column<bool>(),

			q.get_column<bool>(),
			q.get_column<int>(),
			q.get_column<int>(),

			q.get_column<bool>(),
			q.get_column<int>(),
			static_cast<DpiOp>(q.get_column<int>()),

			static_cast<ImageFormat>(q.get_column<int>())
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
