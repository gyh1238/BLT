# EarthRendering Free: not redistributed

The asset files that belong in this folder are third-party content from the
Unity Asset Store. The Asset Store EULA does not permit redistributing them, so
they are not in this repository even though the package is free.

**The `.meta` files are kept on purpose.** They are Unity-generated GUID
mappings, not vendor content, and the scene references the assets by GUID. As
long as you restore the files into this exact folder, the existing `.meta`
files keep their GUIDs and `Assets/Scenes/SampleScene.unity` resolves the Earth
materials, textures and skybox without any manual relinking.

## Restore

1. In Unity, open **Window > Asset Store**, search for **EarthRendering Free**,
   and import it.
2. Move the imported contents into `Assets/EarthRendering Free/` so the paths
   match the `.meta` files already here (`Earth_color_shadow.png`,
   `Earth_night_cloud.png`, `Earth.mat`, `Earth.shader`, `Atmosphere.shader`,
   `EarthAtmosphere.mat`, `Skybox.mat`, `Galaxy*.png`, `Sphere128.FBX`,
   `CameraCtrl.cs`).
3. Let Unity reimport. If the Earth renders pink, a material lost its shader
   reference: reassign `Earth.shader` on `Earth.mat`.

Without this asset the scene still runs; the globe renders untextured.
