#include "db.h"

#include <print>

Connection::Connection(Database &db) : db(db) {
	db.open();
}

Database::Database(const char *db_path) : db_path(db_path) {
}

int Database::exec(const char *query) const {
	char *error_msg;
	int res = sqlite3_exec(db, query, nullptr, nullptr, &error_msg);

	if (res) {
		std::println("sqlite error: {}", error());
		sqlite3_free(error_msg);
	}

	return res;
}

bool Database::open() {
	if (opened) {
		std::println("failed to open database, only one connection allowed");
		return false;
	}


	int err = sqlite3_open(db_path, &db);
	if (err) {
		std::println("failed to open database: {} ", error());
		opened = false;
	} else {
		std::println("opened database");
		opened = true;
	}

	return err == 0;
}

bool Database::close() {
	if (!opened) {
		return true;
	}

	int err = sqlite3_close(db);
	if (err) {
		std::println("failed to close database: {}", error());
	} else {
		std::println("closed database");
		opened = false;
	}

	return err == 0;
}

const char *Database::error() const {
	return sqlite3_errmsg(db);
}

bool Database::prepare(sqlite3_stmt **stmt, const char *query) const {
	return sqlite3_prepare_v2(db, query, -1, stmt, nullptr) == SQLITE_OK;
}

Connection Database::connection() {
	return Connection{*this};
}

Connection::~Connection() {
	db.close();
}

int Connection::exec(const char *query) const {
	return db.exec(query);
}

bool Connection::prepare(sqlite3_stmt **stmt, const char *query) const {
	return db.prepare(stmt, query);
}

const char *Connection::error() const {
	return db.error();
}

Query Connection::query(const char *q) {
	return {*this, q};
}

int Query::bind(const int idx, const int val) const {
	int err = sqlite3_bind_int(stmt, idx, val);
	if (err) {
		std::println("failed to bind value: {}", conn.error());
	}
	return err;
}

int Query::bind(const int idx, const char *val) const {
	int err = sqlite3_bind_text(stmt, idx, val, -1, SQLITE_STATIC);
	if (err) {
		std::println("failed to bind value: {} ", conn.error());
	}
	return err;
}

int Query::bind(const int val) {
	return bind(++bind_counter, val);
}

int Query::bind(const char *val) {
	return bind(++bind_counter, val);
}

bool Query::next_step() const {
	return sqlite3_step(stmt) == SQLITE_ROW;
}

bool Query::exec() const {
	return sqlite3_step(stmt) == SQLITE_DONE;
}
