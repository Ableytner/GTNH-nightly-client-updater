# GTNH daily client updater

This Python script can update your GT New Horizons instance to the newest specified daily version, or to the version used on a specified server.

## Get started

Clone this repository, and rename `config.json.template` to `config.json`.

Then open the file and fill in your `INSTANCE_PATH`.

Whenever you want to update your instance, run `start.bat`.

## config.json

This file is used to customize the installer.

The following entries are allowed in `config.json`:

| name | description | required | example value | default value |
| --- | --- | --- | --- | --- |
| INSTANCE_PATH | the path to your client instance | yes | C:\\Users\\<your_user>\\AppData\\Roaming\\PrismLauncher\\instances\\<your_instance_name> | / |
| SERVER_HOSTNAME | hostname of your server to fetch daily version from | no | your.server.hostname | / |
| ADDITIONAL_MODS | a list of names of additional mods | no | spark-1.9.19-forge1710.jar | / |
| GITHUB_TOKEN | used to download daily versions not available on my download mirror | no | github_pat_XXXXXXXX_XXXXXXXX | / |
| CURRENTLY_INSTALLED | the currently installed daily version | no, set automatically | 279 | / |

A fully setup `config.json` could look like this:
```json
{
    "INSTANCE_PATH": "C:\\Users\\<your_user>\\AppData\\Roaming\\PrismLauncher\\instances\\<your_instance_name>",
    "SERVER_HOSTNAME": "your.server.hostname",
    "ADDITIONAL_MODS": [
        "spark-1.9.19-forge1710.jar"
    ],
    "GITHUB_TOKEN": "github_pat_XXXXXXXX_XXXXXXXX"
}
```

## Fetch installed daily version from your own server

If the installed daily version is posted in your servers' MOTD, it can be detected automatically.

To configure this, set `SERVER_HOSTNAME` to your servers' hostname in `config.json`.

The expected format in the MOTD is:
```
daily-XXX
```
or
```
dailyXXX
```
somewhere within the MOTD.

> [!TIP]  
> If you use my [docker image](https://github.com/Ableytner/GTNH-server), this information is automatically set.

## Add additional mods

If you want to add some additional mods to your instance, add them to `ADDITIONAL_MODS` in `config.json`.

The .jar file of your mod can be either in this directory, or already installed in your client.

> [!WARNING]  
> All additional mods not listed in `config.json` are deleted on every update!

## Download daily client from Github

If you want to download a daily build older than 5 days, or my download mirror isn't available, you need to provide a Github access token.

To create this token:
* head to https://github.com/settings/personal-access-tokens/new
* Set `Token name` to something descriptive.
* Set `Expiration` to a reasonable value. Tokens without an expiration date ARE NOT RECOMMENDED!
* For `Permissions` you don't need to select anything, as it will ony read from public repositories.

After generating the token, copy its value and save it under `GITHUB_TOKEN` in `config.json`.

Now, whenever the download from my download mirror fails, Github is used as a fallback.
