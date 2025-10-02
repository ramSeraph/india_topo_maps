
import torch
from pathlib import Path
import subprocess
import sys
from multiprocessing import Process, Queue
import os

def get_files_to_process(processed_dir, txt_dir):
    all_files = [p for p in Path(processed_dir).glob('*.jpg')]
    processed_files = [f.stem for f in Path(txt_dir).glob('*.json')]
    files_to_process = [p for p in all_files if p.stem not in processed_files]
    return files_to_process

def run_ocr(gpu_id, files_chunk, queue):
    try:
        env = os.environ.copy()
        if gpu_id >= 0:
            env["CUDA_VISIBLE_DEVICES"] = str(gpu_id)

        cmd = [sys.executable, "surya_text.py"] + [str(f) for f in files_chunk]
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True, env=env)
        
        for line in process.stdout:
            print(f"[GPU-{gpu_id if gpu_id >= 0 else 'CPU'}] {line.strip()}", flush=True)
        
        process.wait()
        if process.returncode != 0:
            queue.put(f"Error processing on {'GPU ' + str(gpu_id) if gpu_id >= 0 else 'CPU'}")

    except Exception as e:
        queue.put(f"Exception on {'GPU ' + str(gpu_id) if gpu_id >= 0 else 'CPU'}: {e}")


def main():
    if not torch.cuda.is_available():
        print("CUDA is not available. Running on CPU.")
        num_gpus = 0
    else:
        num_gpus = torch.cuda.device_count()
        print(f"Found {num_gpus} GPUs.")

    processed_dir = 'processed'
    txt_dir = 'text'
    
    files_to_process = get_files_to_process(processed_dir, txt_dir)
    if not files_to_process:
        print("No new files to process.")
        return

    print(f"Found {len(files_to_process)} files to process.")

    if num_gpus == 0:
        # Run on CPU if no GPUs
        run_ocr(-1, files_to_process, Queue())
        return

    files_chunks = [[] for _ in range(num_gpus)]
    for i, file in enumerate(files_to_process):
        files_chunks[i % num_gpus].append(file)

    processes = []
    error_queue = Queue()

    for i in range(num_gpus):
        if files_chunks[i]:
            p = Process(target=run_ocr, args=(i, files_chunks[i], error_queue))
            processes.append(p)
            p.start()

    for p in processes:
        p.join()

    while not error_queue.empty():
        print(error_queue.get())

if __name__ == "__main__":
    main()
