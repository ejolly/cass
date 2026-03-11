/**
 * init — interactive project setup.
 */
import type { CAC } from "cac";
import consola from "consola";
import { match } from "ts-pattern";

export function register(cli: CAC): void {
  cli.command("init", "Interactive project setup").action(async () => {
    const prompts = await import("@clack/prompts");
    const { configFilePath, parseCanvasCourseUrl, parseClassroomUrl, updateConfig } = await import(
      "@/actions/config.ts"
    );

    prompts.intro("cassa init");

    let cfgPath = await configFilePath();
    if (!cfgPath) {
      const { join } = await import("node:path");
      cfgPath = join(process.cwd(), "cass.toml");
      await Bun.write(cfgPath, "");
      consola.info(`Created ${cfgPath}`);
    }

    const canvasUrl = await prompts.text({
      message: "Canvas course URL",
      placeholder: "https://canvas.ucsd.edu/courses/12345",
      validate: (val) => {
        if (!val) return "URL is required";
        if (!parseCanvasCourseUrl(val)) return "Invalid Canvas course URL";
      },
    });
    if (prompts.isCancel(canvasUrl)) {
      prompts.cancel();
      process.exit(0);
    }

    const [baseUrl, courseId] = parseCanvasCourseUrl(canvasUrl as string)!;

    const canvasToken = await prompts.text({
      message: "Canvas API token",
      placeholder: "paste your token here",
    });
    if (prompts.isCancel(canvasToken)) {
      prompts.cancel();
      process.exit(0);
    }

    if (canvasToken) {
      const { join, dirname } = await import("node:path");
      const tokenPath = join(dirname(cfgPath), ".canvastoken");
      await Bun.write(tokenPath, (canvasToken as string).trim());
      consola.success("Saved .canvastoken");
    }

    const classroomUrl = await prompts.text({
      message: "GitHub Classroom URL (optional, press Enter to skip)",
      placeholder: "https://classroom.github.com/classrooms/...",
    });

    const updates: Record<string, unknown> = {
      canvasBaseUrl: baseUrl,
      canvasCourseId: courseId,
    };

    if (classroomUrl && !prompts.isCancel(classroomUrl)) {
      const urlId = parseClassroomUrl(classroomUrl as string);
      if (urlId) {
        updates.classroomUrl = classroomUrl;
        updates.classroomUrlId = urlId;

        try {
          const { ghApiList } = await import("@/apis/github/client.ts");
          const { z } = await import("zod");
          const ClassroomSchema = z.object({ id: z.number(), name: z.string(), url: z.string() });
          const classrooms = await ghApiList("classrooms", ClassroomSchema);
          const found = classrooms.find(
            (c: { id: number; name: string; url: string }) =>
              (classroomUrl as string).includes(String(c.id)) ||
              (classroomUrl as string).includes(c.name),
          );
          if (found) {
            updates.classroomGhId = found.id;
            updates.classroomTitle = found.name;
            consola.success(`Resolved classroom: ${found.name} (id=${found.id})`);
          } else {
            consola.warn("Classroom URL saved but gh_id could not be resolved");
          }
        } catch {
          consola.warn("Could not resolve classroom (gh CLI unavailable?)");
        }
      } else {
        consola.warn("Invalid classroom URL, skipping");
      }
    }

    await updateConfig(cfgPath, updates as never);
    consola.success(`Config saved to ${cfgPath}`);

    const { getConfig } = await import("@/actions/config.ts");
    const { checkPrerequisites } = await import("@/actions/doctor.ts");
    const cfg = await getConfig();
    const checks = await checkPrerequisites(cfg);
    for (const c of checks) {
      const prefix = "  ".repeat(c.indent);
      match(c.status)
        .with("ok", () => consola.success(`${prefix}${c.name}: ${c.detail}`))
        .with("warn", () => consola.warn(`${prefix}${c.name}: ${c.detail}`))
        .with("error", () => consola.error(`${prefix}${c.name}: ${c.detail}`))
        .exhaustive();
    }

    prompts.outro("Setup complete!");
  });
}
