#!/usr/bin/env python3
"""
Respaldo diario de los archivos de Docker Compose de OpenMediaVault a GitHub.

- Copia solo *.yml, *.yaml y *.env de la carpeta de Compose (raíz y un nivel
  de subcarpetas). Nunca copia datos de las apps (p. ej. tailscale/var_lib).
- Reemplaza por CHANGEME el valor de toda variable cuyo nombre parezca un
  secreto (PASSWORD, SECRET, TOKEN, KEY, CLAIM...), en .yml y en .env.
- Los .env se guardan como <nombre>.env.example.
- Antes de hacer commit, busca cadenas largas tipo token/clave que hayan
  quedado. Si encuentra alguna, NO sube nada y termina con error.
- Solo hace commit y push si algo cambió.

Uso en el NAS (como root):
    python3 /root/NASConfig/scripts/backup_compose.py
Opciones de prueba:
    --no-push      hace todo menos el push
    --no-git       solo genera la carpeta compose/ (no toca git)
"""
import argparse
import datetime
import math
import os
import re
import shutil
import subprocess
import sys

# ---- Configuración -------------------------------------------------------
SRC_DIR = "/srv/mergerfs/mergpool/appdata/compose"
REPO_DIR = "/root/NASConfig"
REMOTE = "git@github.com:NeonGE/NASConfig.git"
BRANCH = "main"
SSH_KEY = "/root/.ssh/nasconfig_deploy"
DEST_SUBDIR = "compose"            # carpeta dentro del repo
PLACEHOLDER = "CHANGEME"
EXTENSIONS = (".yml", ".yaml", ".env")
# -------------------------------------------------------------------------

SENSITIVE_KEY = re.compile(
    r"(PASSW(OR)?D|(^|_)PASS($|_)|SECRET|TOKEN|API_?KEY|(^|_)KEY($|_)|"
    r"CLAIM|CREDENTIAL|PRIVATE|AUTH_?KEY|SALT|COOKIE)",
    re.IGNORECASE,
)

# KEY=valor, KEY: valor, - KEY=valor, "KEY": valor, # - KEY=valor
LINE_RE = re.compile(
    r"^(?P<pre>\s*(?:#\s*)?(?:-\s*)?)"
    r"(?P<q>[\"']?)(?P<key>[A-Za-z_][A-Za-z0-9_.]*)(?P=q)"
    r"(?P<sep>\s*(?:=|:(?=\s|$))\s*)"
    r"(?P<val>.*?)"
    r"(?P<post>\s+#.*)?$"
)

URL_CRED_RE = re.compile(r"(://[^:/@\s]+):([^@\s]+)@")

# Cadenas que parecen secretos: 24+ caracteres sin "/" ni espacios
TOKENISH_RE = re.compile(r"[A-Za-z0-9_\-+.]{24,}")


def redact_value(val: str) -> str:
    v = val.strip()
    if not v or v.startswith(("${", "#")) or v in ('""', "''"):
        return val
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        inner = v[1:-1]
        if not inner or inner.startswith("${"):
            return val
        return f"{v[0]}{PLACEHOLDER}{v[0]}"
    return PLACEHOLDER


def sanitize_line(line: str) -> str:
    nl = "\n" if line.endswith("\n") else ""
    body = line[:-1] if nl else line
    body = URL_CRED_RE.sub(rf"\1:{PLACEHOLDER}@", body)
    m = LINE_RE.match(body)
    if m and SENSITIVE_KEY.search(m.group("key")):
        new_val = redact_value(m.group("val"))
        body = (
            m.group("pre") + m.group("q") + m.group("key") + m.group("q")
            + m.group("sep") + new_val + (m.group("post") or "")
        )
    return body + nl


def entropy(s: str) -> float:
    counts = {c: s.count(c) for c in set(s)}
    return -sum(n / len(s) * math.log2(n / len(s)) for n in counts.values())


def find_leaks(text: str):
    leaks = []
    for i, line in enumerate(text.splitlines(), 1):
        for tok in TOKENISH_RE.findall(line):
            # Nombres de variable tipo FORGEJO__database__DB_TYPE no cuentan
            parts = [p for p in tok.split("_") if p]
            if len(parts) > 1 and all(p.isalnum() and len(p) <= 12
                                      for p in parts):
                continue
            has_digit = any(c.isdigit() for c in tok)
            has_alpha = any(c.isalpha() for c in tok)
            if has_digit and has_alpha and entropy(tok) > 3.5:
                leaks.append((i, tok[:6] + "…"))
    return leaks


def collect_files(src: str):
    """Archivos de la raíz y de un nivel de subcarpetas, sin ocultos."""
    out = []
    for name in sorted(os.listdir(src)):
        p = os.path.join(src, name)
        if name.startswith("."):
            continue
        if os.path.isfile(p) and name.endswith(EXTENSIONS):
            out.append(name)
        elif os.path.isdir(p):
            for sub in sorted(os.listdir(p)):
                sp = os.path.join(p, sub)
                if (not sub.startswith(".") and os.path.isfile(sp)
                        and sub.endswith(EXTENSIONS)):
                    out.append(os.path.join(name, sub))
    return out


def build_tree(src: str, dest: str) -> int:
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest)
    problems = []
    files = collect_files(src)
    for rel in files:
        with open(os.path.join(src, rel), encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        clean = "".join(sanitize_line(l) for l in lines)
        out_rel = rel + ".example" if rel.endswith(".env") else rel
        for ln, preview in find_leaks(clean):
            problems.append(f"{out_rel}:{ln} -> {preview}")
        out_path = os.path.join(dest, out_rel)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(clean)
    if problems:
        shutil.rmtree(dest)
        print("ABORTADO: posibles secretos sin limpiar. No se subió nada.",
              file=sys.stderr)
        print("Muévelos a variables con nombre tipo *_PASSWORD/*_TOKEN/*_KEY:",
              file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        sys.exit(2)
    return len(files)


def git(*args, check=True, capture=False):
    env = dict(os.environ)
    env["GIT_SSH_COMMAND"] = (
        f"ssh -i {SSH_KEY} -o IdentitiesOnly=yes "
        f"-o StrictHostKeyChecking=accept-new"
    )
    return subprocess.run(
        ["git", "-C", REPO_DIR, *args], check=check, env=env,
        capture_output=capture, text=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=SRC_DIR)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--no-git", action="store_true")
    a = ap.parse_args()

    global REPO_DIR
    if a.repo:
        REPO_DIR = a.repo

    if not a.no_git:
        if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
            subprocess.run(["git", "clone", REMOTE, REPO_DIR], check=True,
                           env={**os.environ, "GIT_SSH_COMMAND":
                                f"ssh -i {SSH_KEY} -o IdentitiesOnly=yes "
                                f"-o StrictHostKeyChecking=accept-new"})
        # El repo del NAS es un espejo: se alinea con GitHub antes de copiar.
        git("fetch", "origin", BRANCH)
        git("checkout", "-q", "-B", BRANCH, f"origin/{BRANCH}")
        git("reset", "-q", "--hard", f"origin/{BRANCH}")

    n = build_tree(a.src, os.path.join(REPO_DIR, DEST_SUBDIR))
    print(f"{n} archivos procesados.")
    if a.no_git:
        return

    git("add", "-A", DEST_SUBDIR)
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        print("Sin cambios. Nada que subir.")
        return
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    git("-c", "user.name=NAS Backup", "-c", "user.email=nas@localhost",
        "commit", "-q", "-m", f"Respaldo automático {stamp}")
    if a.no_push:
        print("Commit creado (sin push).")
        return
    git("push", "-q", "origin", f"HEAD:{BRANCH}")
    print("Respaldo subido a GitHub.")


if __name__ == "__main__":
    main()
