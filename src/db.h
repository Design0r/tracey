#pragma once
#include <sqlite3.h>
#include <string>
#include <print>

#include <cstdio>

class Query;
class Connection;

class Database {
	bool opened = false;
	sqlite3 *db = nullptr;
	const char *db_path;

public:
	explicit Database(const char *db_path);

	int exec(const char *query) const;

	bool open();
	bool close();

	[[nodiscard]] const char *error() const;
	bool prepare(sqlite3_stmt **stmt, const char *query) const;

	[[nodiscard]] Connection connection();
};

class Transaction {
	Database &db;

public:
	explicit Transaction(Database &db) : db(db) {
		db.exec("BEGIN TRANSACTION;");
	}

	~Transaction() {
		rollback();
	}

	int commit() const {
		return db.exec("COMMIT TRANSACTION;");
	}

	int rollback() const {
		return db.exec("ROLLBACK TRANSACTION;");
	}
};

class Connection {
	Database &db;

public:
	explicit Connection(Database &db);
	~Connection();

	int exec(const char *query) const;
	bool prepare(sqlite3_stmt **stmt, const char *query) const;
	[[nodiscard]] const char *error() const;
	Query query(const char *q);
};

template<typename T>
struct ColumnReader;

template<>
struct ColumnReader<int> {
	static int read(sqlite3_stmt *stmt, const int idx) {
		return sqlite3_column_int(stmt, idx);
	}
};

template<>
struct ColumnReader<const char *> {
	static const char *read(sqlite3_stmt *stmt, const int idx) {
		return reinterpret_cast<const char *>(sqlite3_column_text(stmt, idx));
	}
};

template<>
struct ColumnReader<std::string> {
	static std::string read(sqlite3_stmt *stmt, const int idx) {
		const auto *text = sqlite3_column_text(stmt, idx);
		if (!text) return {};
		const int len = sqlite3_column_bytes(stmt, idx);
		return {reinterpret_cast<const char *>(text), static_cast<size_t>(len)};
	}
};

class Query {
	Connection &conn;
	std::string_view query;
	sqlite3_stmt *stmt = nullptr;
	int bind_counter = 0;

public:
	Query(Connection &conn, const char *query) : conn(conn), query(query) {
		if (!conn.prepare(&stmt, query)) {
			std::println("prepare failed: {}", conn.error());
		}
	}

	~Query() {
		if (stmt) {
			std::println("finalizing");
			sqlite3_finalize(stmt);
		}
	}

	int bind(int idx, int val) const;
	int bind(int idx, const char *val) const;

	int bind(int val);
	int bind(const char *val);

	template<typename T>
	T get_column(const int idx) {
		return ColumnReader<T>::read(stmt, idx);
	}

	bool next_step() const;
	bool exec() const;
};
