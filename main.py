import os
import re
import shutil
import zipfile

from abllib import PersistentStorage, log
import mcstatus
import requests

logger = log.get_logger()

CONFIG_PATH = "./config.json"

def main():
    log.initialize(log.LogLevel.INFO)
    log.add_console_handler()

    PersistentStorage.initialize(CONFIG_PATH)

    if not os.path.isfile(CONFIG_PATH):
        raise FileNotFoundError()
    
    if "SERVER_HOSTNAME" in PersistentStorage or "SERVER_IP" in PersistentStorage:
        server_host: str = PersistentStorage.get("SERVER_HOSTNAME", None) or PersistentStorage.get("SERVER_IP", None)

        if not ":" in server_host:
            target_daily = get_daily_build_number(server_host)
        else:
            host, port = server_host.split(":", maxsplit=1)
            target_daily = get_daily_build_number(host, port)

    if target_daily is not None:
        logger.info(f"found target daily build {target_daily}")
    else:
        target_daily = ask_user_for_input()
        if target_daily is None:
            exit(0)
    
    if "CURRENTLY_INSTALLED" in PersistentStorage and target_daily == PersistentStorage["CURRENTLY_INSTALLED"]:
        logger.info("target daily build is already installed, exiting...")
        return

    try:
        client_zip = download_daily_zip_from_mirror(target_daily, new_java=True)
    except Exception as e:
        logger.exception()

        if "GITHUB_TOKEN" not in PersistentStorage or PersistentStorage["GITHUB_TOKEN"] == "":
            raise Exception("You have to provide a GITHUB_TOKEN in config.json in order to download from github")

        client_zip = download_daily_zip_from_github(PersistentStorage["GITHUB_TOKEN"], target_daily, new_java=True) # TODO: read new_java from instance dir

    extracted_client_zip = extract_daily_zip(client_zip)

    add_additional_mods(PersistentStorage["ADDITIONAL_MODS"], PersistentStorage["INSTANCE_PATH"], extracted_client_zip)

    backup_zip = backup_instance(PersistentStorage["INSTANCE_PATH"])

    try:
        install_new_daily(extracted_client_zip, PersistentStorage["INSTANCE_PATH"])
    except Exception as e:
        logger.error("Install failed, restoring backup...")
        restore_instance(PersistentStorage["INSTANCE_PATH"], backup_zip)

        raise e

    PersistentStorage["CURRENTLY_INSTALLED"] = target_daily
    PersistentStorage.save_to_disk()

    logger.info(f"update to daily-{target_daily} succeeded!")
    shutil.rmtree(ensure_temp_dir())

def ask_user_for_input() -> int | None:
    user_input = "a"
    while not user_input.isdigit() and user_input != "":
        user_input = input(f"which daily version do you want to install: ")

    if user_input.isdigit():
        return int(user_input)
    
    return None

def get_daily_build_number(server_host: str, server_port: int = 25565) -> int | None:
    server = mcstatus.JavaServer(server_host, server_port, timeout=10)

    try:
        status = server.status()
        motd = str(status.motd.raw)
    except ConnectionResetError:
        logger.warning(f"cannot reach server {server_host}:{server_port}")
        return None

    matches = re.findall(r"(daily-?)(\d+)", motd)

    if len(matches) == 0:
        logger.warning(f"could not discern daily version from motd '{motd}'")
        return None
    if len(matches) > 1:
        logger.warning(f"found multiple daily versions in motd '{motd}'")
        return None
    
    return int(matches[0][1])

def download_daily_zip_from_mirror(daily_build: int, new_java: bool = False) -> str:
    if not new_java:
        raise Exception("mirror server download only supports Java 21")

    storage_path = ensure_storage_dir()
    download_path = os.path.join(storage_path, "download", f"daily{daily_build}-client.zip")

    if os.path.isfile(download_path):
        logger.info("using cached client zip file")
        return download_path

    session = requests.Session()
    download_url = f"https://files.ableytner.at/daily{daily_build}-client.zip"

    r = session.head(download_url)
    if r.status_code != 200:
        raise Exception("client zip file not found on ableytner's mirror server")

    logger.info("downloading client zip file from ableytner's mirror server...")
    with session.get(download_url, stream=True) as archive:
        archive.raise_for_status()

        with open(download_path, 'wb') as f:
            for chunk in archive.iter_content(chunk_size=512 * 1024): 
                if chunk: # filter out keep-alive new chunks
                    f.write(chunk)

    return download_path

def download_daily_zip_from_github(github_token: str, daily_build: int, new_java: bool = False) -> str:
    storage_path = ensure_storage_dir()
    download_path = os.path.join(storage_path, "download", f"daily{daily_build}-client.zip")

    if os.path.isfile(download_path):
        logger.info("using cached client zip file")
        return download_path

    session = requests.Session()
    session.headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    r = session.get("https://api.github.com/repos/GTNewHorizons/DreamAssemblerXXL/actions/workflows/daily-modpack-build.yml/runs", params={"per_page": "100"})

    runs = r.json()["workflow_runs"]
    target_run = None
    for run in runs:
        if run["run_number"] == daily_build:
            target_run = run
    if target_run is None:
        raise Exception("target daily build could not be fetched, maybe its older than 100 days?")

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

    logger.info("downloading client zip file from github, this will take a few minutes...")
    with session.get(target_artifact['archive_download_url'], stream=True) as archive:
        archive.raise_for_status()

        with open(download_path, 'wb') as f:
            for chunk in archive.iter_content(chunk_size=512 * 1024): 
                if chunk: # filter out keep-alive new chunks
                    f.write(chunk)

    return download_path

def extract_daily_zip(client_zip_path: str) -> str:
    tempdir = ensure_temp_dir()

    with zipfile.ZipFile(client_zip_path, "r") as f:
        f.extractall(tempdir)

    zipfiles_names = [item for item in os.listdir(tempdir) if item.endswith(".zip")]

    if len(zipfiles_names) > 0:
        # extract inner zip file
        inner_client_zip = os.path.join(tempdir, zipfiles_names[0])
        inner_client_zip_dir = os.path.join(tempdir, "client")

        os.mkdir(inner_client_zip_dir)
        with zipfile.ZipFile(inner_client_zip, "r") as f:
            f.extractall(inner_client_zip_dir)

        return os.path.join(inner_client_zip_dir, "GT New Horizons daily")
    else:
        return os.path.join(tempdir, "GT New Horizons daily")

def install_new_daily(daily_path: str, instance_path: str) -> None:
    remove_and_move(os.path.join(daily_path, "libraries"), os.path.join(instance_path, "libraries"))
    remove_and_move(os.path.join(daily_path, "patches"), os.path.join(instance_path, "patches"))
    remove_and_move(os.path.join(daily_path, "mmc-pack.json"), os.path.join(instance_path, "mmc-pack.json"))
    remove_and_move(os.path.join(daily_path, ".minecraft", "config"), os.path.join(instance_path, ".minecraft", "config"))
    remove_and_move(os.path.join(daily_path, ".minecraft", "mods"), os.path.join(instance_path, ".minecraft", "mods"))

def backup_instance(instance_path: str) -> str:
    storage_path = ensure_storage_dir()
    backup_dir = os.path.join(storage_path, "backup")

    backup_ids = []
    for backup in os.listdir(backup_dir):
        matches = re.findall(r"(backup-)(\d+)(.zip)", backup)
        if len(matches) == 0:
            raise Exception(f"Couldn't find backup_id in filename {backup}")

        backup_ids.append(int(matches[0][1]))

    backup_ids.sort()

    # delete old backup if over limit
    if len(backup_ids) > 5:
        os.remove(os.path.join(backup_dir, f"backup-{backup_ids[0]}.zip"))

    backup_path = os.path.join(backup_dir, f"backup-{backup_ids[-1] + 1}.zip")

    logger.info(f"backing up instance to '{backup_path}'...")

    backup_file = shutil.make_archive(backup_path, "zip", instance_path)
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
        logger.info(f"added additional mod {os.path.basename(mod_file)}")

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
