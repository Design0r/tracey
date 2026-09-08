#include "application.h"
#include "db.h"
#include "store.h"

int main() {
	std::setvbuf(stdout, nullptr, _IONBF, 0);
	Database db("../test.db");
	Store store(db);

	Application app(store);
	app.run();

	return 0;
}
