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

	auto migration_count = std::size(MIGRATIONS);

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

static void bind_profile(Query &q, const ExportProfile &p) {
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
}

static bool save_formats(Connection &conn, const ExportProfile &p) {
	auto clear = conn.query("DELETE FROM export_format WHERE profile_id = ?;");
	clear.bind(p.id);
	if (!clear.exec()) return false;

	for (const ImageFormat format: p.formats) {
		// OR IGNORE: the primary key rejects a format listed twice.
		auto q = conn.query("INSERT OR IGNORE INTO export_format (profile_id, format) VALUES (?, ?);");
		q.bind(p.id);
		q.bind(format);
		if (!q.exec()) return false;
	}

	return true;
}

int Store::create_profile(const ExportProfile &p) const {
	auto conn = db.connection();
	Transaction tx(db);

	auto q = conn.query(
		"INSERT INTO export_profile ("
		"name, "
		"color_space_enabled, color_space, color_space_op, color_space_embedd, "
		"bit_depth_enabled, bit_depth, keep_alpha, "
		"resolution_enabled, width, height, "
		"dpi_enabled, dpi, dpi_op"
		") "
		"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id;");
	bind_profile(q, p);

	if (!q.next_step()) {
		std::println("failed to create profile {}", db.error());
		return 0;
	}

	ExportProfile created = p;
	created.id = q.get_column<int>(0);
	// The RETURNING row keeps the statement open until it is stepped to the end.
	q.exec();

	if (!save_formats(conn, created) || !tx.commit()) {
		std::println("failed to create profile {}", db.error());
		return 0;
	}

	return created.id;
}

bool Store::update_profile(const ExportProfile &p) const {
	auto conn = db.connection();
	Transaction tx(db);

	auto q = conn.query(
		"UPDATE export_profile SET "
		"name = ?, "
		"color_space_enabled = ?, color_space = ?, color_space_op = ?, color_space_embedd = ?, "
		"bit_depth_enabled = ?, bit_depth = ?, keep_alpha = ?, "
		"resolution_enabled = ?, width = ?, height = ?, "
		"dpi_enabled = ?, dpi = ?, dpi_op = ? "
		"WHERE id = ?;");
	bind_profile(q, p);
	q.bind(p.id);

	if (!q.exec() || !save_formats(conn, p) || !tx.commit()) {
		std::println("failed to update profile {}: {}", p.id, db.error());
		return false;
	}

	return true;
}

std::vector<ExportProfile> Store::get_profiles() const {
	std::vector<ExportProfile> data;

	auto conn = db.connection();
	auto q = conn.query(
		"SELECT id, name, "
		"color_space_enabled, color_space, color_space_op, color_space_embedd, "
		"bit_depth_enabled, bit_depth, keep_alpha, "
		"resolution_enabled, width, height, "
		"dpi_enabled, dpi, dpi_op "
		"FROM export_profile ORDER BY name;");

	while (q.next_step()) {
		data.emplace_back(
			q.get_column<int>(0),
			q.get_column<std::string>(1),

			q.get_column<bool>(2),
			static_cast<ColorSpace>(q.get_column<int>(3)),
			static_cast<ColorSpaceOp>(q.get_column<int>(4)),
			q.get_column<bool>(5),

			q.get_column<bool>(6),
			static_cast<BitDepth>(q.get_column<int>(7)),
			q.get_column<bool>(8),

			q.get_column<bool>(9),
			q.get_column<int>(10),
			q.get_column<int>(11),

			q.get_column<bool>(12),
			q.get_column<int>(13),
			static_cast<DpiOp>(q.get_column<int>(14)),
			std::vector<ImageFormat>{}
		);
	}

	auto formats = conn.query("SELECT profile_id, format FROM export_format ORDER BY rowid;");
	while (formats.next_step()) {
		const int profile_id = formats.get_column<int>(0);
		for (auto &profile: data) {
			if (profile.id == profile_id) {
				profile.formats.push_back(static_cast<ImageFormat>(formats.get_column<int>(1)));
			}
		}
	}

	return data;
}

bool Store::delete_profile(const ExportProfile &profile) const {
	auto conn = db.connection();
	Transaction tx(db);

	// Foreign keys are off by default in SQLite, so the ON DELETE CASCADE can't be relied on.
	auto formats = conn.query("DELETE FROM export_format WHERE profile_id = ?;");
	formats.bind(profile.id);

	auto q = conn.query("DELETE FROM export_profile WHERE id = ?;");
	q.bind(profile.id);

	if (!formats.exec() || !q.exec() || !tx.commit()) {
		std::println("failed to delete profile {}: {}", profile.id, db.error());
		return false;
	}

	return true;
}
