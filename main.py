import json
import os
import re
import shutil
import zipfile

import mcstatus
import requests

CONFIG_PATH = "./config.json"

def main():
    if not os.path.isfile(CONFIG_PATH):
        raise FileNotFoundError()
    
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    
    if "SERVER_HOSTNAME" in config:
        server_host: str = config["SERVER_HOSTNAME"]
    elif "SERVER_IP" in config:
        server_host: str = config["SERVER_IP"]
    else:
        raise KeyError()
    
    if not ":" in server_host:
        target_nightly = get_nightly_build_number(server_host)
    else:
        host, port = server_host.split(":", maxsplit=1)
        target_nightly = get_nightly_build_number(host, port)
    
    print(f"found target nightly build {target_nightly}")

    client_zip = download_nightly_zip(config["GITHUB_TOKEN"], target_nightly, new_java=True) # TODO: read new_java from instance dir

    extracted_client_zip = extract_nigthly_zip(client_zip)

    add_additional_mods(config["ADDITIONAL_MODS"], config["INSTANCE_PATH"], extracted_client_zip)

    backup_zip = backup_instance(config["INSTANCE_PATH"])

    try:
        install_new_nightly(extracted_client_zip, config["INSTANCE_PATH"])
    except Exception as e:
        print("Install failed, restoring backup...")
        restore_instance(config["INSTANCE_PATH"], backup_zip)

        raise e

    print(f"update to nightly-{target_nightly} succeeded!")
    shutil.rmtree(ensure_temp_dir())

def get_nightly_build_number(server_host: str, server_port: int = 25565) -> int:
    server = mcstatus.JavaServer(server_host, server_port)

    try:
        status = server.status()
        motd = str(status.motd.raw)
    except ConnectionResetError:
        raise Exception(f"cannot reach server {server_host}:{server_port}")

    matches = re.findall(r"(nightly-?)(\d+)", motd)

    if len(matches) == 0:
        raise ValueError(f"could not discern nightly version from motd '{motd}'")
    if len(matches) > 1:
        raise ValueError(f"found multiple nightly versions in motd '{motd}'")
    
    return int(matches[0][1])

def download_nightly_zip(github_token: str, nightly_build: int, new_java: bool = False) -> str:
    storage_path = ensure_storage_dir()
    download_path = os.path.join(storage_path, "download", f"nightly{nightly_build}-client.zip")

    if os.path.isfile(download_path):
        print("using cached client zip file")
        return download_path

    session = requests.Session()
    session.headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    r = session.get("https://api.github.com/repos/GTNewHorizons/DreamAssemblerXXL/actions/runs", params={"per_page": "100"})

    runs = r.json()["workflow_runs"]
    target_run = None
    for run in runs:
        if run["run_number"] == nightly_build:
            target_run = run
    if target_run is None:
        raise Exception("target nigthly build could not be fetched, maybe its older than 100 days?")

    r = session.get(f"{target_run['url']}/artifacts")

    artifacts = r.json()["artifacts"]
    target_artifact = None
    if new_java:
        for artifact in artifacts:
            if "mmcprism-new-java" in artifact["name"]:
                target_artifact = artifact
    else:
        for artifact in artifacts:
            if "mmcprism-java8" in artifact["name"]:
                target_artifact = artifact
    if target_artifact is None:
        raise Exception("target client zipfile could not be fetched")

    print("downloading client zip file, this will take a few minutes...")
    r = session.get(f"{target_artifact['archive_download_url']}")

    with open(download_path, "wb") as f:
        f.write(r.content)

    return download_path

def extract_nigthly_zip(client_zip_path: str) -> str:
    tempdir = ensure_temp_dir()

    with zipfile.ZipFile(client_zip_path, "r") as f:
        f.extractall(tempdir)
    
    inner_client_zip = os.path.join(tempdir, os.listdir(tempdir)[0])
    inner_client_zip_dir = os.path.join(tempdir, "client")

    os.mkdir(inner_client_zip_dir)
    with zipfile.ZipFile(inner_client_zip, "r") as f:
        f.extractall(inner_client_zip_dir)

    return os.path.join(inner_client_zip_dir, "GT New Horizons nightly")

def install_new_nightly(nightly_path: str, instance_path: str) -> None:
    remove_and_move(os.path.join(nightly_path, "libraries"), os.path.join(instance_path, "libraries"))
    remove_and_move(os.path.join(nightly_path, "patches"), os.path.join(instance_path, "patches"))
    remove_and_move(os.path.join(nightly_path, "mmc-pack.json"), os.path.join(instance_path, "mmc-pack.json"))
    remove_and_move(os.path.join(nightly_path, ".minecraft", "config"), os.path.join(instance_path, ".minecraft", "config"))
    remove_and_move(os.path.join(nightly_path, ".minecraft", "mods"), os.path.join(instance_path, ".minecraft", "mods"))

def backup_instance(instance_path: str) -> str:
    storage_path = ensure_storage_dir()
    backup_dir = os.path.join(storage_path, "backup")

    backup_id = 0
    for backup in os.listdir(backup_dir):
        matches = re.findall(r"(backup-)(\d+)(.zip)", backup)
        if len(matches) > 0 and int(matches[0][1]) > backup_id:
            backup_id = int(matches[0][1])

    backup_path = os.path.join(backup_dir, f"backup-{backup_id}.zip")
    print(f"backing up instance to '{backup_path}'...")

    backup_file = shutil.make_archive(f"backup-{backup_id}", "zip", instance_path)
    shutil.move(backup_file, backup_path)

    return backup_path

def restore_instance(instance_path: str, backup_zip: str) -> None:
    if not os.path.isfile(backup_zip):
        raise FileNotFoundError()
    with zipfile.ZipFile(backup_zip, "r") as f:
        if f.testzip() is not None:
            raise Exception("Backup zip is corrupted, cannot restore")

    shutil.rmtree(instance_path)
    os.makedirs(instance_path, exist_ok=True)
    with zipfile.ZipFile(backup_zip, "r") as f:
        f.extractall(instance_path)

def add_additional_mods(additional_mods: list[str], instance_path: str, extracted_client_zip: str):
    mods_dir = os.path.join(extracted_client_zip, ".minecraft", "mods")
    
    for additional_mod in additional_mods:
        if additional_mod.startswith("http://") or additional_mod.startswith("https://"):
            raise NotImplementedError("Mod downloads are not yet implemented")
        elif additional_mod.endswith(".jar"):
            mod_file = additional_mod
            if not os.path.isfile(mod_file):
                mod_file = os.path.join(instance_path, ".minecraft", "mods", os.path.basename(additional_mod))
            if not os.path.isfile(mod_file):
                raise FileNotFoundError()
        else:
            raise ValueError("Unknown additional mod type")
        
        shutil.copy(mod_file, mods_dir)
        print(f"added additional mod {os.path.basename(mod_file)}")

def ensure_storage_dir() -> str:
    storage_path = os.path.abspath("./storage")

    os.makedirs(os.path.join(storage_path, "backup"), exist_ok=True)
    os.makedirs(os.path.join(storage_path, "download"), exist_ok=True)

    return storage_path

def ensure_temp_dir() -> str:
    temp_path = os.path.abspath("./temp")

    if os.path.isdir(temp_path):
        shutil.rmtree(temp_path)

    os.makedirs(temp_path)

    return temp_path

def remove_and_move(source: str, destination: str) -> None:
    if os.path.isfile(source):
        os.remove(destination)
        shutil.move(source, os.path.join(destination))
    elif os.path.isdir(source):
        shutil.rmtree(destination)
        shutil.move(source, os.path.join(destination, ".."))
    else:
        raise FileNotFoundError()

if __name__ == "__main__":
    main()
