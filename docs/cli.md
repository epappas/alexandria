# CLI Reference

## `alxia`

```
Usage: python -m alexandria [OPTIONS] COMMAND [ARGS]...                        
                                                                                
 alexandria — local-first single-user knowledge engine.                         
                                                                                
 Accumulates your gathered knowledge (raw sources, compiled wiki pages, event   
 streams, AI conversations) and exposes it via MCP to connected agents like     
 Claude Code for retroactive query and synthesis.                               
                                                                                
 alexandria is NOT a chat client. Interactive conversations happen in your      
 existing MCP-capable agent (Claude Code, Cursor, Codex, ...). alexandria is    
 the knowledge engine those agents connect to.                                  
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --version  -V        Print version and exit.                                 │
│ --help               Show this message and exit.                             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ init           Initialize ~/.alexandria/ and the global workspace.           │
│ status         Show daemon, workspaces, and basic state.                     │
│ paste          One-shot capture from stdin into raw/local/.                  │
│ doctor         Run health checks across the install.                         │
│ ingest         Compile a source into the wiki (staged + verified).           │
│ query          Answer from the wiki by searching all knowledge sources.      │
│ watch          Watch a directory and auto-ingest on changes.                 │
│ lint           Find wiki rot: stale citations, missing sources.              │
│ why            Belief explainability + provenance + history (read-only).     │
│ synthesize     Generate temporal synthesis digest.                           │
│ sync           Pull from configured sources.                                 │
│ captures       List captured conversations.                                  │
│ workspace      Workspace management.                                         │
│ project        Project workspace management.                                 │
│ db             Database operations.                                          │
│ backup         Backup and restore.                                           │
│ reindex        Rebuild SQLite indexes from filesystem.                       │
│ beliefs        Belief management and traceability.                           │
│ source         Source adapters.                                              │
│ subscriptions  Subscription inbox.                                           │
│ mcp            MCP integration.                                              │
│ eval           Evaluation metrics.                                           │
│ secrets        Secret vault.                                                 │
│ hooks          Auto-save hooks.                                              │
│ capture        Conversation capture.                                         │
│ daemon         Daemon management.                                            │
│ logs           Structured log viewer.                                        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia init`

```
Usage: python -m alexandria init [OPTIONS]                                     
                                                                                
 Initialize ~/.alexandria/ and the global workspace.                            
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --path,--home        PATH  Override the alexandria home directory (default:  │
│                            ~/.alexandria).                                   │
│ --force                    Re-run init even if the home directory already    │
│                            exists.                                           │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia status`

```
Usage: python -m alexandria status [OPTIONS]                                   
                                                                                
 Show daemon, workspaces, and basic state.                                      
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit JSON instead of human output.                           │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia doctor`

```
Usage: python -m alexandria doctor [OPTIONS]                                   
                                                                                
 Run health checks across the install.                                          
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia ingest`

```
Usage: python -m alexandria ingest [OPTIONS] SOURCE                            
                                                                                
 Compile a source into the wiki (staged + verified).                            
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    source      TEXT  File, directory, URL, or git repo URL. [required]     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT  Override the current workspace.                   │
│ --topic              TEXT  Topic directory for the wiki page (default:       │
│                            inferred).                                        │
│ --dry-run                  Preview without running (single file only).       │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia query`

```
Usage: python -m alexandria query [OPTIONS] QUESTION                           
                                                                                
 Answer from the wiki by searching all knowledge sources.                       
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    question      TEXT  The question to answer. [required]                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --json                     Output as JSON.                                   │
│ --save                     Save the answer as a wiki page.                   │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia watch`

```
Usage: python -m alexandria watch [OPTIONS] [PATH]                             
                                                                                
 Watch a directory and auto-ingest on changes.                                  
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   path      [PATH]  Directory to watch. [default: .]                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --debounce           INTEGER  Debounce interval in ms. [default: 500]        │
│ --help                        Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia lint`

```
Usage: python -m alexandria lint [OPTIONS]                                     
                                                                                
 Find wiki rot: stale citations, missing sources.                               
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --fix                      Auto-fix deterministic issues.                    │
│ --verbose    -v                                                              │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia why`

```
Usage: python -m alexandria why [OPTIONS] QUERY                                
                                                                                
 Belief explainability + provenance + history (read-only).                      
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    query      TEXT  Topic, subject, or belief id to look up. [required]    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w                  TEXT  Override the current workspace.       │
│ --since                          TEXT  Only beliefs current at or after this │
│                                        date.                                 │
│ --history        --no-history          Include superseded beliefs.           │
│                                        [default: history]                    │
│ --json                                 Emit JSON.                            │
│ --help                                 Show this message and exit.           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia synthesize`

```
Usage: python -m alexandria synthesize [OPTIONS]                               
                                                                                
 Generate temporal synthesis digest.                                            
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --period             INTEGER  Period in days. [default: 7]                   │
│ --dry-run                     Preview without writing.                       │
│ --force                       Skip eval gate check.                          │
│ --help                        Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia sync`

```
Usage: python -m alexandria sync [OPTIONS] [SOURCE_ID]                         
                                                                                
 Pull from configured sources.                                                  
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   source_id      [SOURCE_ID]  Sync a specific source (by ID).                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia paste`

```
Usage: python -m alexandria paste [OPTIONS]                                    
                                                                                
 One-shot capture from stdin into raw/local/.                                   
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --title      -t      TEXT  Title for the captured note. Used as the filename │
│                            slug.                                             │
│ --workspace  -w      TEXT  Override the current workspace.                   │
│ --content            TEXT  Inline content (otherwise stdin is read).         │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia workspace list`

```
Usage: python -m alexandria workspace list [OPTIONS]                           
                                                                                
 List all workspaces.                                                           
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Emit JSON.                                                   │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia workspace use`

```
Usage: python -m alexandria workspace use [OPTIONS] SLUG                       
                                                                                
 Set the current workspace.                                                     
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    slug      TEXT  The workspace slug to switch to. [required]             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia project create`

```
Usage: python -m alexandria project create [OPTIONS] NAME                      
                                                                                
 Create a new project workspace.                                                
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    name      TEXT  Workspace name (also used as slug). [required]          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --slug                 TEXT  Override the slug derived from the name.        │
│ --description  -d      TEXT  Short workspace description.                    │
│ --help                       Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia project list`

```
Usage: python -m alexandria project list [OPTIONS]                             
                                                                                
 List project workspaces.                                                       
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --global    --no-global      Include the 'global' workspace.                 │
│                              [default: global]                               │
│ --json                       Emit JSON.                                      │
│ --help                       Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia source add`

```
Usage: python -m alexandria source add [OPTIONS] ADAPTER_TYPE                  
                                                                                
 Configure a new source adapter.                                                
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    adapter_type      TEXT  Adapter type:                                   │
│                              local|git-local|github|rss|imap|youtube|notion… │
│                              [required]                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ *  --name            -n      TEXT  Human-readable name for this source.      │
│                                    [required]                                │
│    --workspace       -w      TEXT                                            │
│    --path                    TEXT  Path (for local/folder/archive adapters). │
│    --repo-url                TEXT  Git repo URL.                             │
│    --owner                   TEXT  GitHub owner.                             │
│    --repo                    TEXT  GitHub repo name.                         │
│    --token-ref               TEXT  Secret vault ref for token.               │
│    --feed-url                TEXT  RSS/Atom feed URL.                        │
│    --urls                    TEXT  Comma-separated URLs (youtube).           │
│    --repos                   TEXT  Comma-separated repo IDs (huggingface).   │
│    --page-ids                TEXT  Comma-separated Notion page IDs.          │
│    --database-ids            TEXT  Comma-separated Notion DB IDs.            │
│    --imap-host               TEXT  IMAP server host.                         │
│    --imap-user               TEXT  IMAP username.                            │
│    --imap-pass-ref           TEXT  Vault ref for IMAP password.              │
│    --imap-folder             TEXT  IMAP folder. [default: INBOX]             │
│    --from-allowlist          TEXT  Comma-separated sender filter.            │
│    --help                          Show this message and exit.               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia source list`

```
Usage: python -m alexandria source list [OPTIONS]                              
                                                                                
 List configured source adapters.                                               
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia subscriptions list`

```
Usage: python -m alexandria subscriptions list [OPTIONS]                       
                                                                                
 Show pending subscription items.                                               
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --status     -s      TEXT  Filter: pending|ingested|dismissed                │
│                            [default: pending]                                │
│ --adapter            TEXT  Filter by adapter type (rss|imap).                │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia subscriptions poll`

```
Usage: python -m alexandria subscriptions poll [OPTIONS]                       
                                                                                
 Poll subscription sources (RSS + IMAP).                                        
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --source             TEXT  Poll a specific source.                           │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia beliefs list`

```
Usage: python -m alexandria beliefs list [OPTIONS]                             
                                                                                
 List beliefs in the workspace.                                                 
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w           TEXT                                               │
│ --topic                   TEXT  Filter by topic.                             │
│ --current        --all          Show only current beliefs.                   │
│                                 [default: current]                           │
│ --json                                                                       │
│ --help                          Show this message and exit.                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia beliefs cleanup`

```
Usage: python -m alexandria beliefs cleanup [OPTIONS]                          
                                                                                
 Dedup beliefs and remove orphans.                                              
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --dry-run                  Preview without applying.                         │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia secrets set`

```
Usage: python -m alexandria secrets set [OPTIONS] REF                          
                                                                                
 Store an encrypted secret.                                                     
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    ref      TEXT  Secret reference name. [required]                        │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia secrets list`

```
Usage: python -m alexandria secrets list [OPTIONS]                             
                                                                                
 List stored secrets (metadata only).                                           
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia hooks install`

```
Usage: python -m alexandria hooks install [OPTIONS] CLIENT                     
                                                                                
 Install hooks into a client.                                                   
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    client      TEXT  Client: claude-code | codex [required]                │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia hooks verify`

```
Usage: python -m alexandria hooks verify [OPTIONS] [CLIENT]                    
                                                                                
 Verify hook installation.                                                      
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   client      [CLIENT]  Client to verify (default: all).                     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia mcp serve`

```
Usage: python -m alexandria mcp serve [OPTIONS]                                
                                                                                
 Start the stdio MCP server.                                                    
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT  Pin the server to one workspace (pinned mode).    │
│                            Omit for open mode.                               │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia mcp install`

```
Usage: python -m alexandria mcp install [OPTIONS] CLIENT                       
                                                                                
 Register alexandria as an MCP server in a client.                              
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    client      TEXT  Client to install into: claude-code | claude-desktop  │
│                        | cursor | codex | windsurf                           │
│                        [required]                                            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT  Pin the installed server to one workspace.        │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia mcp status`

```
Usage: python -m alexandria mcp status [OPTIONS]                               
                                                                                
 Show MCP server registration status.                                           
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia eval run`

```
Usage: python -m alexandria eval run [OPTIONS]                                 
                                                                                
 Run evaluation metrics.                                                        
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --metric     -m      TEXT  Metric: M1|M2|M4|M5|all [default: all]            │
│ --workspace  -w      TEXT                                                    │
│ --json                                                                       │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia eval report`

```
Usage: python -m alexandria eval report [OPTIONS]                              
                                                                                
 Show evaluation history.                                                       
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --since              TEXT  [default: 30d]                                    │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia daemon start`

```
Usage: python -m alexandria daemon start [OPTIONS]                             
                                                                                
 Start the supervised-subprocess daemon.                                        
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --foreground  -f        Run in foreground (no daemonize).                    │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia daemon status`

```
Usage: python -m alexandria daemon status [OPTIONS]                            
                                                                                
 Show daemon process state.                                                     
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON.                                              │
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia capture conversation`

```
Usage: python -m alexandria capture conversation [OPTIONS] [TRANSCRIPT]        
                                                                                
 Capture a conversation transcript.                                             
                                                                                
╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│   transcript      [TRANSCRIPT]  Path to transcript file.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --client     -c      TEXT  [default: claude-code]                            │
│ --workspace  -w      TEXT                                                    │
│ --detach                   Return immediately, capture in background.        │
│ --reason             TEXT  Capture reason (e.g., pre-compact).               │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia captures`

```
Usage: python -m alexandria captures [OPTIONS]                                 
                                                                                
 List captured conversations.                                                   
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --workspace  -w      TEXT                                                    │
│ --status             TEXT                                                    │
│ --help                     Show this message and exit.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia db migrate`

```
Usage: python -m alexandria db migrate [OPTIONS]                               
                                                                                
 Apply pending schema migrations.                                               
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --dry-run          Show pending migrations without applying them.            │
│ --help             Show this message and exit.                               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia db status`

```
Usage: python -m alexandria db status [OPTIONS]                                
                                                                                
 Show schema version and pending migrations.                                    
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

## `alxia backup create`

```
Usage: python -m alexandria backup create [OPTIONS]                            
                                                                                
 Create a backup tarball of ~/.alexandria/.                                     
                                                                                
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --output  -o      PATH  Destination archive path (default:                   │
│                         ~/.alexandria/backups/alexandria-backup-<ts>.tar.gz… │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

