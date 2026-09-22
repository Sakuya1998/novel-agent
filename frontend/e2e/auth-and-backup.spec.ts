import { expect, test } from "@playwright/test";

test("cookie session survives refresh and protects the workspace", async ({ page }, testInfo) => {
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  const suffix = `${testInfo.project.name}-${testInfo.workerIndex}-${Date.now().toString(36)}`
    .replace(/[^a-z0-9-]/gi, "-")
    .toLowerCase();
  const username = `e2e_${suffix}`;
  const displayName = `E2E ${testInfo.project.name}`;
  const novelTitle = `Cookie smoke ${testInfo.project.name}`;

  await page.goto("/");
  const authDialog = page.getByRole("dialog", { name: "工作区身份" });
  if (!await authDialog.isVisible().catch(() => false)) {
    await page.getByTitle("登录工作区").click();
  }
  await authDialog.getByRole("button", { name: "注册工作区" }).click();
  await authDialog.getByLabel("用户名", { exact: true }).fill(username);
  await authDialog.getByLabel("显示名称").fill(displayName);
  await authDialog.getByLabel("工作区名称").fill(`${displayName} workspace`);
  await authDialog.getByLabel("密码").fill("browser-test-password");
  await authDialog.getByRole("button", { name: "提交注册" }).click();
  await expect(authDialog).toBeHidden();
  await expect(page.getByTitle(`${displayName} · owner`)).toBeVisible();

  const cookies = await page.context().cookies();
  expect(cookies.find((cookie) => cookie.name === "novel_agent_session")?.httpOnly).toBe(true);
  expect(cookies.find((cookie) => cookie.name === "novel_agent_csrf")?.httpOnly).toBe(false);
  expect(await page.evaluate(() => localStorage.getItem("novel_agent_access_token"))).toBeNull();

  await page.reload();
  await expect(page.getByTitle(`${displayName} · owner`)).toBeVisible();
  expect(consoleErrors).toEqual([]);

  const createStatus = await page.evaluate(async (title) => {
    const csrf = document.cookie
      .split(";")
      .map((item) => item.trim())
      .find((item) => item.startsWith("novel_agent_csrf="))
      ?.split("=", 2)[1] ?? "";
    const response = await fetch("/api/novels", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": decodeURIComponent(csrf) },
      body: JSON.stringify({ title, genre: "科幻", inspiration: "deterministic browser smoke", total_chapters: 1 }),
    });
    return response.status;
  }, novelTitle);
  expect(createStatus).toBe(200);

  await page.reload();
  await expect(page.getByRole("button", { name: `打开《${novelTitle}》` })).toBeVisible();
  await page.getByRole("button", { name: "工具" }).click();
  await page.getByRole("menuitem", { name: /导入与导出/ }).click();
  const transferDialog = page.getByRole("dialog", { name: "导入与导出" });
  await transferDialog.getByLabel("导出格式").selectOption("backup");
  await transferDialog.getByLabel("导出备份密码").fill("e2e-backup-password");
  const downloadPromise = page.waitForEvent("download");
  await transferDialog.getByRole("button", { name: "导出文件" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/\.novel-backup\.enc$/);

  await transferDialog.getByRole("button", { name: "关闭" }).click();
  await page.getByTitle(`${displayName} · owner`).click();
  await page.getByRole("dialog", { name: "工作区身份" }).getByRole("button", { name: "退出登录" }).click();
  await expect(page.getByTitle("登录工作区")).toBeVisible();
  expect((await page.context().cookies()).some((cookie) => cookie.name === "novel_agent_session")).toBe(false);
  expect(consoleErrors).toEqual([]);
  page.removeAllListeners("console");
  expect(await page.evaluate(async () => (await fetch("/api/novels", { credentials: "include" })).status)).toBe(401);
});
