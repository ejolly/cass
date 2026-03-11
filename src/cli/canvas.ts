/**
 * Canvas CLI commands — registers all canvas-* commands.
 */
import type { CAC } from "cac";

import { register as announcements } from "./commands/canvas-announcements.ts";
import { register as assignments } from "./commands/canvas-assignments.ts";
import { register as files } from "./commands/canvas-files.ts";
import { register as modules } from "./commands/canvas-modules.ts";
import { register as overview } from "./commands/canvas-overview.ts";
import { register as quizzes } from "./commands/canvas-quizzes.ts";
import { register as sync } from "./commands/canvas-sync.ts";
import { register as tabs } from "./commands/canvas-tabs.ts";

export function registerCanvasCommands(cli: CAC): void {
  overview(cli);
  modules(cli);
  assignments(cli);
  quizzes(cli);
  files(cli);
  announcements(cli);
  tabs(cli);
  sync(cli);
}
