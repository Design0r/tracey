#include "application.h"
#include <print>
#include "ui.h"

Application::Application(Store &s) : store(s), ui(Ui(s)) {
	std::println("starting application");
}

Application::~Application() {
	std::println("closing application");
}

void Application::run() {
	ui.run();
}
