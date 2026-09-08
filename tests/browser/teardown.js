export default async function teardown() {
  const response = await fetch("http://127.0.0.1:8011/__test_shutdown", {
    method: "POST",
    headers: { "X-Test-Shutdown": process.env.TRADECHECK_TEST_SHUTDOWN },
  });
  if (!response.ok)
    throw new Error("Could not shut down the temporary test server.");
}
