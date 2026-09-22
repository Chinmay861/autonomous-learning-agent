import platform
import psutil
import subprocess
from dataclasses import dataclass

@dataclass
class HardwareInfo:
    cpu_name: str
    cpu_cores: int
    cpu_threads: int
    ram_total_gb: float
    gpu_name: str | None
    gpu_vram_gb: float | None
    os_name: str
    disk_free_gb: float

def detect_hardware() -> HardwareInfo:
    cpu_cores = psutil.cpu_count(logical=False) or 0
    cpu_threads = psutil.cpu_count(logical=True) or 0
    ram_total_gb = psutil.virtual_memory().total / (1024**3)
    
    os_name = platform.system() + " " + platform.release()
    disk_free_gb = psutil.disk_usage('/').free / (1024**3)
    
    cpu_name = platform.processor()
    
    gpu_name = None
    gpu_vram_gb = None
    
    try:
        # Try to use nvidia-smi
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total', '--format=csv,noheader'],
            capture_output=True, text=True, check=True
        )
        output = result.stdout.strip().split('\n')[0]
        parts = output.split(', ')
        if len(parts) >= 2:
            gpu_name = parts[0]
            # VRAM is usually in 'MiB' like '4096 MiB'
            vram_str = parts[1].replace(' MiB', '')
            gpu_vram_gb = float(vram_str) / 1024
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return HardwareInfo(
        cpu_name=cpu_name,
        cpu_cores=cpu_cores,
        cpu_threads=cpu_threads,
        ram_total_gb=ram_total_gb,
        gpu_name=gpu_name,
        gpu_vram_gb=gpu_vram_gb,
        os_name=os_name,
        disk_free_gb=disk_free_gb
    )

def recommend_model(hardware: HardwareInfo) -> dict:
    ram = hardware.ram_total_gb
    vram = hardware.gpu_vram_gb or 0
    
    if ram >= 32 and vram >= 16:
        primary = "llama3.1:70b"
        fast = "llama3.1:8b"
    elif ram >= 16 or vram >= 8:
        primary = "llama3.1:8b"
        fast = "phi3:mini"
    else:
        primary = "phi3:mini"
        fast = "qwen2.5:0.5b"
        
    return {
        "primary_model": primary,
        "fast_model": fast
    }
