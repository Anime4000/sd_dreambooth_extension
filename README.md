# Dreambooth Extension for Stable-Diffusion-WebUI
Please refer to original repo for main description - https://github.com/d8ahazard/sd_dreambooth_extension  

## 1.5 Stable Plus  
This is a fork based on older commits with D8 extension in pre-SDXL rework form, as it's generally most stable and usable one, if you are not interested in SDXL.  
There are some features that are either ported, or newly implemented in this fork.  
### Min SNR  
Saunderez worked hard on making it work, and i ported it to older version. Use at value of 5, but for experiments value slider can be set up to 100.  
### Expanded Scheduling of Offset Noise  
In my trainings i found out that having offset noise at same value for prolonged amount of steps can cause it to burn-in, and make images washed, instead of contrasty. I implemented a simple linear scheduling for it, and added randomization range, if you want to further offseet linearity. Proven effective in my own trainings.  
![изображение](https://github.com/Anzhc/sd_dreambooth_extension_1.5-stable-plus/assets/133806049/92750f43-cf4c-4fa0-9d8b-e5a9683b66fd)

### Loss Curve Scale  
New feature that i've implemented recently. It is derived from idea of v-prediction, which scales reward based on timestep of noise scheduler.  
This curve scales loss value based on timestep, which did improve overall quality drastically and made model faster to converge, while seemingly not producing burn, or overfit. In fact, we found noticeable reduction in overfit to specific pose in character we baked for test.
Though, it is important to note, that this, and feature above, are based only on my own speculations and don't have papers to prove efficiency, so use with caution.  
![изображение](https://github.com/Anzhc/sd_dreambooth_extension_1.5-stable-plus/assets/133806049/da51f34e-5b73-4707-be22-e926b60ebaf2)  
It is supposed to adjust loss based on curve smth like this:  
![изображение](https://github.com/Anzhc/sd_dreambooth_extension_1.5-stable-plus/assets/133806049/b8a09f84-de25-4675-bb33-e51c8f2aaec5)
But im really not a math or code guy, and used GPT4 for making it, so this might not align well with reality.

I don't have much examples yet, as it's really recent, but here is style training, with every setting matching with exception of loss curve.
![изображение](https://github.com/Anzhc/sd_dreambooth_extension_1.5-stable-plus/assets/133806049/d3920ee5-ee2c-4288-8fec-d15f55169cb3)
My tests shown significant improvement from utilization of those simple, practically free, enhancements, but please, always test for yourself.  

### Expanded bracket prompts support []  
Originally, it was only [filewords], basically.  
I've added next triggers: [style], [generic], [styfil05], [genfil05]  
They will generate and match with prompts from specific lists, and let you create more general, or less specific regularization datasets.  
It's hard to test efficiency of those in various situations due to amount of images i usually use, so will be grateful if you would test that.  
P.S. You need to create new folders for [...05] variants, as they will match to both random and filewords promps, which can end up be either full random, or full filewords, if enough images are present in reg folder.
