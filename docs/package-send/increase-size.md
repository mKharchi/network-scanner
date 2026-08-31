## Implementation plan

### Phase 1 — Map the existing deployment flow

Before changing code, have the AI inspect the complete path:

```text
DeployPackagePanel.tsx
        ↓
gui/src/api/client.ts
        ↓
POST /api/actions
        ↓
api_server.py
        ↓
action_service.create_action()
        ↓
deploy_package_to_client()
        ↓
server_lib.send_message()
        ↓
Client package receiver
        ↓
verification/extraction
```

Also inspect:

- `actions` database schema
- existing package-related tables, if any
- client-side package storage
- existing chunking implementation
- existing SHA-256 verification
- cleanup/error handling

**Do not modify anything during this phase.**

The goal is to understand what can be reused.

---

# Phase 2 — Introduce package storage

Create a dedicated package-storage layer.

For example:

```text
server/
├── server_components/
│   ├── action_service.py
│   ├── package_service.py       ← new
│   └── ...
│
└── storage/
    └── packages/
```

`package_service.py` should be responsible for:

```text
store_package()
get_package()
get_package_metadata()
delete_package()
package_exists()
calculate_sha256()
```

The important principle is:

> **The package service handles bytes/files. The action service handles actions.**

---

# Phase 3 — Add package metadata to the database

Create a `packages` table rather than putting the ZIP into `actions`.

Something conceptually like:

```sql
packages
--------
id
package_id
filename
size_bytes
sha256
storage_path
created_at
```

You can also add:

```text
status
uploaded_by
```

if useful.

The important part is that **there is no ZIP/BLOB/Base64 field**.

For example:

```text
package_id:
pkg-7e91c2...

filename:
my-client-package.zip

size_bytes:
483721932

sha256:
8f3a...

storage_path:
storage/packages/pkg-7e91c2....zip
```

---

# Phase 4 — Create a dedicated upload endpoint

Currently you're doing:

```text
POST /api/actions
    packageDataBase64
```

Remove the package data from that request.

Instead create something conceptually like:

```text
POST /api/packages
```

The GUI sends the ZIP to this endpoint.

The server:

1. Checks extension/type.
2. Checks size.
3. Enforces **500 MB maximum**.
4. Streams the upload to disk.
5. Calculates SHA-256.
6. Creates the package metadata record.
7. Returns the `package_id`.

For example:

```json
{
  "package_id": "pkg-7e91c2",
  "filename": "client-v2.zip",
  "size_bytes": 483721932,
  "sha256": "..."
}
```

### Important

Don't do:

```python
file_bytes = request.read()
```

for a 500 MB upload if you can avoid it.

Prefer streaming:

```text
HTTP request
     ↓
small chunk
     ↓
disk
     ↓
small chunk
     ↓
disk
```

This keeps server memory usage reasonable.

---

# Phase 5 — Change the GUI

`DeployPackagePanel.tsx` should no longer do:

```text
ZIP
 ↓
Base64
 ↓
JSON
 ↓
/api/actions
```

Instead:

```text
ZIP
 ↓
POST /api/packages
 ↓
package_id
 ↓
POST /api/actions
```

So the GUI process becomes:

```text
1. User selects ZIP
2. Check ≤ 500 MB
3. Upload ZIP
4. Receive package_id
5. Create deployment action using package_id
6. Monitor deployment
```

The deployment action becomes tiny:

```json
{
  "package_id": "pkg-7e91c2",
  "timeout": 1800
}
```

instead of potentially hundreds of megabytes of JSON.

---

# Phase 6 — Modify `client.ts`

Change the API abstraction.

Instead of:

```typescript
deployPackage({
    packageDataBase64,
    ...
})
```

you want something closer to:

```typescript
uploadPackage(file);
```

and:

```typescript
deployPackage({
    packageId,
    targets,
    ...
})
```

This separation is important because it makes the API model much clearer:

```text
uploadPackage()
       ↓
Package

deployPackage()
       ↓
Action referencing Package
```

---

# Phase 7 — Modify `action_service.py`

This is where the current failure originates.

Currently the package is eventually included in:

```text
parameters
```

which is inserted into `actions`. Your log shows the MySQL failure occurring during that insertion.

Change the deployment action so it receives:

```json
{
  "package_id": "pkg-7e91c2"
}
```

Then:

```python
package = package_service.get_package(package_id)
```

The action service obtains the package **from storage**, not from the database action payload.

Then the existing deployment/chunking mechanism can operate on the stored file.

---

# Phase 8 — Adapt the transfer mechanism

This is important.

If your current transfer implementation expects:

```python
raw_bytes = base64.b64decode(package_data)
```

don't simply replace that with:

```python
raw_bytes = open(...).read()
```

because that would just move the memory problem from Base64 to a 500 MB byte array.

Instead make the transfer file-aware:

```text
package.zip
     ↓
read chunk
     ↓
send chunk
     ↓
read next chunk
     ↓
send
     ↓
...
```

Your existing chunking mechanism can probably be reused.

For example:

```text
storage file
     │
     ├── chunk 1 → client
     ├── chunk 2 → client
     ├── chunk 3 → client
     ├── ...
     └── chunk N → client
```

This is where the existing deployment implementation should be preserved as much as possible.

---

# Phase 9 — Keep SHA-256 verification

You already have package integrity verification according to the existing deployment description.

Keep it.

The server has:

```text
package.sha256
```

The client receives the chunks and reconstructs:

```text
package.zip
```

Then:

```text
SHA256(client_file)
        ↓
compare
        ↓
server SHA256
```

If they don't match:

```text
DEPLOYMENT FAILED
```

If they match:

```text
extract
    ↓
validate
    ↓
swap/update
```

---

# Phase 10 — Set the actual 500 MB limit

Centralize it.

Don't have:

```text
200 MB in one file
500 MB in another
4777 MB somewhere else
```

Have one configuration value:

```python
MAX_PACKAGE_SIZE_BYTES = 500 * 1024 * 1024
```

Ideally configurable through your server configuration/environment:

```text
MAX_PACKAGE_SIZE_MB=500
```

Then both the upload API and deployment logic use the same source.

The GUI can also expose the same conceptual limit:

```typescript
const MAX_PACKAGE_BYTES = 500 * 1024 * 1024;
```

---

# Phase 11 — Timeout

The AI's original idea of scaling the timeout based on number of chunks isn't necessarily bad, but don't blindly use:

```text
3 seconds × every 128 KB chunk
```

because that can produce unnecessarily huge timeouts.

Instead, think in terms of:

```text
package size
+
expected transfer rate
+
safety margin
```

For example, a 500 MB package over a slow 10 Mbps link takes roughly **7 minutes** just for the theoretical payload transfer.

So the deployment watchdog needs to accommodate realistic network conditions.

Better yet, distinguish:

```text
upload timeout
transfer timeout
client processing timeout
```

rather than treating the entire deployment as one giant timeout.

---

# Phase 12 — Package lifecycle / cleanup

Once packages are stored separately, you need to decide what happens to old packages.

For example:

```text
Package uploaded
      ↓
Used by deployment
      ↓
Keep package
```

But eventually:

```text
unused package
      ↓
retention period
      ↓
delete
```

Don't automatically delete a package immediately after deployment because another client may need the same package.

This gives you a useful future capability:

```text
client A ─┐
client B ─┼──→ package-v2.zip
client C ─┘
```

One uploaded package can be deployed to many clients.

---

# Phase 13 — Error handling

Make failures explicit at each stage:

```text
UPLOAD_FAILED
UPLOAD_TOO_LARGE
INVALID_PACKAGE
PACKAGE_NOT_FOUND
PACKAGE_CORRUPTED
TRANSFER_FAILED
HASH_MISMATCH
EXTRACTION_FAILED
DEPLOYMENT_FAILED
```

This will make the GUI much better too.

Instead of:

> Deployment failed

you can show:

> Package upload failed — file exceeds the 500 MB limit.

or:

> Deployment failed — SHA-256 verification failed.

---

# Phase 14 — Testing

Test the entire flow.

### Size tests

```text
100 MB  → accepted
200 MB  → accepted
499 MB  → accepted
500 MB  → accepted
500 MB + 1 byte → rejected
```

### Package lifecycle

```text
Upload
 ↓
stored
 ↓
metadata created
 ↓
package_id returned
```

### Action

Verify the `actions` row contains:

```json
{
  "package_id": "..."
}
```

and **does not contain package bytes**.

This is particularly important.

### Deployment

```text
Upload
 ↓
Create action
 ↓
Client receives chunks
 ↓
Reassemble
 ↓
SHA-256
 ↓
Extract
 ↓
Deploy
```

### Failure tests

Test:

- nonexistent package ID
- interrupted upload
- interrupted client transfer
- corrupted package
- incorrect SHA-256
- package >500 MB
- multiple clients using the same package

---

# Final architecture

After this change, your system should look like:

```text
                         GUI
                          │
                          │ ZIP ≤ 500 MB
                          ▼
                  ┌─────────────────┐
                  │ Package API     │
                  └────────┬────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │ Package Service │
                  └────────┬────────┘
                           │
                 ┌─────────┴─────────┐
                 ▼                   ▼
          File Storage          MySQL
          package.zip        package metadata
                 │
                 │ package_id
                 ▼
          ┌─────────────────┐
          │ Action Service  │
          └────────┬────────┘
                   │
             DEPLOY_PACKAGE
                   │
             package_id
                   │
                   ▼
             Chunked Transfer
                   │
                   ▼
                Client
                   │
             SHA-256 verify
                   │
               Extract
                   │
                Deploy
```

### The key architectural rule

**`actions` should answer:**

> _"What should the server do?"_

**`packages` should answer:**

> _"What file should be used?"_

**Package storage should answer:**

> _"Where are the actual bytes?"_

That separation fixes your MySQL problem, makes the 500 MB requirement much safer, avoids giant JSON/Base64 requests, and gives you a foundation for package versioning, reuse across clients, cleanup, and eventually resumable uploads.
