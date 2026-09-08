#pragma once

#include "store.h"
#include "ui.h"

auto constexpr APP_NAME = "Luma";
auto constexpr APP_VERSION = "0.1.0";

class Application {
	Store &store;
	Ui ui;

public:
	explicit Application(Store &s);
	~Application();

	void run();
};
