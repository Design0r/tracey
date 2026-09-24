#include "application.h"
#include "db.h"
#include "img.h"
#include "store.h"

int main() {
	std::setvbuf(stdout, nullptr, _IONBF, 0);

	if (!img::init()) {
		return 1;
	}

	{
		Database db("../test.db");
		Store store(db);

		// Scoped so a running export is stopped and joined before libvips shuts down.
		Application app(store);
		app.run();
	}

	img::shutdown();

	return 0;
}
