#include "application.h"
#include "db.h"
#include "store.h"

int main() {
	Database db("../test.db");
	Store s(db);

	Application app(s);
	app.run();

	return 0;
}
