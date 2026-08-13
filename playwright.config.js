// Drives the app in demo mode (synthetic events, writes disabled) so layout
// checks are deterministic and never touch a real calendar.
const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5000",
  },
  webServer: [
    {
      command: ".venv/bin/python server.py",
      url: "http://127.0.0.1:5000/",
      // Deliberately false: these servers carry fixture config in their env, and
      // reusing whatever already happens to be on the port silently runs the
      // whole suite against the wrong data (an already-running zero-accounts
      // instance makes every event assertion fail for no visible reason).
      // Failing loudly on a busy port is the better outcome.
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        WALLCAL_DEMO: "1",
        WALLCAL_DEMO_ACCOUNTS: "2",
        FLASK_SECRET_KEY: "playwright",
      },
    },
    // A second instance with nobody signed in, so the "no calendars connected"
    // empty state is actually rendered by a test rather than only reasoned about.
    {
      command: ".venv/bin/python server.py",
      url: "http://127.0.0.1:5001/",
      // Deliberately false: these servers carry fixture config in their env, and
      // reusing whatever already happens to be on the port silently runs the
      // whole suite against the wrong data (an already-running zero-accounts
      // instance makes every event assertion fail for no visible reason).
      // Failing loudly on a busy port is the better outcome.
      reuseExistingServer: false,
      timeout: 30_000,
      env: {
        PORT: "5001",
        WALLCAL_DEMO: "1",
        WALLCAL_DEMO_ACCOUNTS: "0",
        FLASK_SECRET_KEY: "playwright",
      },
    },
  ],
});
