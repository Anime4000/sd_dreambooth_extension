# Dreambooth Extension for SD 1.5 (512)
This Dreambooth mainly for Anime, code modification from [@Anzhc](https://github.com/Anzhc/)

## 1.5 Stable Plus  
This is a fork based on older commits with D8 extension in pre-SDXL rework form, as it's generally most stable and usable one, if you are not interested in SDXL.

There are some features that are either ported, or newly implemented in this fork.

# VRAM
This fork wont work at 10GB GPU, you must have at least 12GB! A faster GPU is referred as training speed will increase.

# Install
Before you run, please do this:
1. `stable-diffusion-webui` by AUTOMATIC1111
2. Clone this repo into `extensions` folder
   ```
   git clone https://github.com/Anime4000/sd_dreambooth_extension --branch rex-3
   ```
3. Open `venv` Console
   ```
   cd stable-diffusion-webui
   cmd /k "venv\Scripts\activate.bat"
   ```
4. Install Requirements
   ```
   pip install -r extensions\sd_dreambooth_extension\requirements_strict.txt
   ```
5. Install xFormers
   ```
   pip install xformers==0.0.22.post7
   ```
6. Run

# Verify
By default, now this Dreambooth wont check version and install/upgrade, please check the output make sure it's match (or some of it):
```
Initializing Dreambooth
Dreambooth revision: -
[+] xformers version 0.0.22.post4+cu118 installed.
[+] torch version 2.1.0+cu118 installed.
[+] torchvision version 0.16.0+cu118 installed.
[+] accelerate version 0.21.0 installed.
[+] diffusers version 0.21.4 installed.
[+] transformers version 4.30.2 installed.
[+] bitsandbytes version 0.35.4 installed.
```

# Use
Create a dreambooth training project, then press **Load Settings** to load default value for Anime training
