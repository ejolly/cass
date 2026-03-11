#!/usr/bin/env bun
import { registerCanvasCommands } from "@/cli/canvas.ts";
import { registerRootCommands } from "@/cli/index.ts";
/**
 * cassa — CLI entry point. Flat cac commands.
 */
import cac from "cac";
import consola from "consola";

// Ensure all log levels are visible (consola suppresses info in NODE_ENV=test)
consola.level = 4;

const cli = cac("cassa");

registerRootCommands(cli);
registerCanvasCommands(cli);

cli.help();
cli.version("0.1.0");

// Show help when invoked with no command args
const hasCommand = process.argv.slice(2).some((a) => !a.startsWith("-"));
if (
  !hasCommand &&
  !process.argv.includes("--help") &&
  !process.argv.includes("-h") &&
  !process.argv.includes("--version") &&
  !process.argv.includes("-v")
) {
  cli.outputHelp();
}

cli.parse();
