# Dreambooth Extension for SD 1.5 (512)
![20240417015131 3477173320](https://github.com/Anime4000/sd_dreambooth_extension/assets/1908715/997442f6-0204-4339-8c9f-f7df83d78be7)
> [!NOTE]
> This Dreambooth has been modified and tuned for Anime training in SD 1.5 (512x512)

## 1.5 Stable Plus  
This is a fork based on older commits with D8 extension in pre-SDXL rework form, as it's generally most stable and usable one, if you are not interested in SDXL.

There are some features that are either ported, or newly implemented in this fork.

# VRAM
This fork wont work at 10GB GPU, you must have at least 12GB! A faster GPU is referred as training speed will increase.

# Install
Before you run, please do this:
1. `stable-diffusion-webui` by AUTOMATIC1111
2. Run `stable-diffusion-webui` first.
3. Once ready to use, close `stable-diffusion-webui`.
4. Clone this repo into `extensions` folder
   ```
   git clone https://github.com/Anime4000/sd_dreambooth_extension --branch rex-3
   ```
5. Open `venv` Console
   ```
   cd stable-diffusion-webui
   cmd /k "venv\Scripts\activate.bat"
   ```
6. Install Requirements
   ```
   pip install -r extensions\sd_dreambooth_extension\requirements_strict.txt
   ```
7. Run

# Verify
By default, now this Dreambooth wont check version and install/upgrade, please check the output make sure it's match (or some of it):
```
Initializing Dreambooth
Dreambooth revision: -
Skipping pip install because the requirements.txt file does not exist. Make sure you have installed all required dependencies before executing this script.
bitsandbytes>=0.43.0 already include Windows binary, no need to check.
[+] xformers version 0.0.23.post1 installed.
[+] torch version 2.1.2+cu121 installed.
[+] torchvision version 0.16.2+cu121 installed.
[+] accelerate version 0.21.0 installed.
[+] diffusers version 0.21.4 installed.
[+] transformers version 4.30.2 installed.
[+] bitsandbytes version 0.43.1 installed.
```

# Use
Create a dreambooth training project, then press **Load Settings** to load default value for Anime training
