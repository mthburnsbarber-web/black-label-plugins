#!/usr/bin/env node
import { auditWebsite } from './report.mjs';

const args = process.argv.slice(2);
if (args.length === 1 && ['--help', '-h'].includes(args[0])) {
  process.stdout.write('Usage: node audit-site.mjs https://your-business.example\nPrints a dated JSON audit of one public webpage and its discovery files.\n');
  process.exit(0);
}
if (args.length !== 1) {
  process.stderr.write('Expected exactly one public website URL. Use --help for usage.\n');
  process.exit(2);
}
try {
  const report = await auditWebsite(args[0]);
  process.stdout.write(JSON.stringify(report, null, 2) + '\n');
} catch (error) {
  process.stderr.write(JSON.stringify({ error: error.code ?? 'audit_failed', message: error.message }) + '\n');
  process.exitCode = 1;
}
