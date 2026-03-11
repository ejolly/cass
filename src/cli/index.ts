/**
 * Root CLI commands — registers all non-canvas commands.
 */
import type { CAC } from "cac";

import { register as backup } from "./commands/backup.ts";
import { register as del } from "./commands/delete.ts";
import { register as init } from "./commands/init.ts";
import { register as pullRepos } from "./commands/pull-repos.ts";
import { register as pull } from "./commands/pull.ts";
import { register as push } from "./commands/push.ts";
import { register as query } from "./commands/query.ts";
import { register as restore } from "./commands/restore.ts";
import { register as revert } from "./commands/revert.ts";
import { register as status } from "./commands/status.ts";

export function registerRootCommands(cli: CAC): void {
  status(cli);
  init(cli);
  pull(cli);
  push(cli);
  revert(cli);
  query(cli);
  pullRepos(cli);
  del(cli);
  backup(cli);
  restore(cli);
}
