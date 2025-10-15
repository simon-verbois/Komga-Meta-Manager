<p align="center">
  <img src="https://api.visitorbadge.io/api/visitors?path=https%3A%2F%2Fgithub.com%2Fsimon-verbois%2FKomga-Meta-Manager&label=Visitors&countColor=26A65B&style=plastic" alt="Visitor Count" height="28"/>
  <a href="https://github.com/simon-verbois/Komga-Meta-Manager/commits/main"><img src="https://img.shields.io/github/last-commit/simon-verbois/Komga-Meta-Manager?style=plastic" alt="GitHub Last Commit" height="28"/></a>
</p>

# Komga Meta Manager

An automated tool to enrich your Komga manga series metadata using the AniList API, featuring optional translation and persistent caching.

## ✨ Features

  * **Automated Metadata Fetching:** Automatically searches for and fetches **Title**, **Summary**, **Status**, **Genres**, and **Tags** for your Komga series from **AniList**.
  * **Targeted Processing:** Only processes libraries you specify in the configuration.
  * **Translation Support:** Seamlessly translates fetched metadata (like summaries, genres, and tags) into your preferred language using **Google Translate** or **DeepL**.
  * **Smart Updates:** Choose to only fill in empty metadata fields or overwrite existing ones.
  * **Persistent Caching:** Avoid repeated API calls and speed up processing with a persistent translation cache.
  * **Flexible Operation:** Run once manually or enable the built-in scheduler to run the process daily at a set time.
  * **Dry-Run Mode:** Test your configuration and see exactly what changes will be made before applying them to Komga.

## 📷 Example (Before/After)

<img src="images/before.png" alt="Before image - Missing metadata for the series" width="38%">
<img src="images/after.png" alt="After image - Metadata correctly populated by the tool" width="38%">

## 🚀 Installation and Setup

The easiest way to run the Komga Meta Manager is using Docker.

### Prerequisites

1.  A running instance of **Komga**.
2.  A Komga **API Key** (recommended to create a specific read/write user for this tool).
3.  **Docker** and **Docker Compose** installed on your system.

### 1\. Configure the Project

The application is configured using a single YAML file named `config.yml`. It is crucial to set your Komga server details and desired processing logic in this file.

1.  Create a directory for your Komga Meta Manager setup (e.g., `komga-meta-manager`).
2.  Inside this directory, create a subdirectory named `config`.
3.  Create the main configuration file, `config/config.yml`, by starting with the example below:
4.  *(Optional but recommended)* You can also create a file named `config/translations.yml` to define manual translations for specific genres or tags, which overrides the automatic translator.

#### Configuration Parameters Explained

The table below explains every parameter in the `config.yml` file.

| Section | Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| **`system`** | **`dry_run`** | Boolean | `false` | If **`true`**, the script runs without making **any changes** to Komga; it only logs proposed updates. |
| | **`debug`** | Boolean | `false` | Enables verbose logging (DEBUG level) for troubleshooting. |
| | **`scheduler.enabled`** | Boolean | `true` | If **`true`**, the job runs daily at the specified time. If **`false`**, it runs once and the container exits. |
| | **`scheduler.run_at`** | String | `"04:00"` | The time of day to run the job, in **HH:MM** (24-hour) format. Only used if `scheduler.enabled: true`. |
| **`komga`** | **`url`** | String | *Required* | The full URL of your Komga instance (e.g., `https://komga.example.com`). |
| | **`api_key`** | String | *Required* | Your **Komga API Key**. |
| | **`libraries`** | List of Strings | *Required* | A list of the **exact names** of the Komga libraries you want to process. |
| | **`verify_ssl`** | Boolean | `true` | If set to `false`, disables SSL certificate verification (useful for self-signed certificates, but less secure). |
| **`provider`** | **`name`** | String | `"anilist"` | The metadata source to use. Currently, only **`anilist`** is supported. |
| | **`min_score`** | Integer | `80` | The minimum score (from 0 to 100) required for a fuzzy title match to be considered valid. Higher values mean stricter matching. |
| **`processing`** | **`overwrite_existing`** | Boolean | `false` | If **`true`**, fetched metadata will **overwrite** any existing Komga metadata. If **`false`**, it only fills in fields that are currently empty or unlocked. |
| | **`force_unlock`** | Boolean | `false` | If **`true`**, the script will automatically **unlock** any locked metadata fields in Komga before updating them. This allows for a complete refresh of metadata. |
| | **`exclude_series`** | List of Strings | `[]` | A list of exact series titles to **exclude** from processing. |
| | **`update_fields`** | List of Boolean | `[]` | A list of all supported fields, activate those you want with **true**. |
| **`translation`** | **`enabled`** | Boolean | `true` | If **`true`**, metadata (summary, genres, tags) will be translated into the `target_language`. |
| | **`provider`** | String | `"google"` | The translation service to use. Supported: **`google`**, **`deepl`**. |
| | **`deepl.api_key`** | String | *Required if provider is `deepl`* | Your **DeepL API Key**. You can get one [here](https://support.deepl.com/hc/en-us/articles/360021200939-DeepL-API-plans). |
| | **`target_language`** | String | `"fr"` | The ISO 639-1 code for the language you want to translate to (e.g., `fr`, `en`, `es`). |
*Deepl will return a better result, but need an API key to work.*

### 2\. Run with Docker Compose

1.  In the root directory of your project (the one containing the `config` folder), create the `docker-compose.yml` file with the following content:

**`docker-compose.yml`**

```yaml
services:
  komga-meta-manager:
    image: simonverbois/komga-meta-manager
    container_name: komga-meta-manager
    restart: unless-stopped
    environment:
      # Set your timezone
      - TZ=Europe/Brussels 
    volumes:
      # Mount the configuration folder where the app will look for config.yml and cache files
      - ./config:/config
```

2.  Start the container in detached mode:

```bash
docker-compose up -d
```

*To run the job once and remove the container afterwards (e.g., for testing or manual runs without scheduling), use:*
```bash
docker-compose run --rm komga-meta-manager
```

### 3\. Verification

Check the logs to ensure the application is running correctly and connecting to Komga:

```bash
docker logs komga-meta-manager -f
```

## 📜 Changelog

Check the [CHANGELOG.md](CHANGELOG.md) for a complete history of changes and versions.

## ⚙️ Resources

[Dockerhub Repository](https://hub.docker.com/r/simonverbois/komga-meta-manager)

[Komga Homepage](https://komga.org/)
