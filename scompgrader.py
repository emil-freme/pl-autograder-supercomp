import difflib
import glob
import json
import os
import platform
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, asdict

@dataclass
class PLTest:
    name: str
    max_points: float
    points: float = 0
    output: str = ""

@dataclass
class PLResult:
    gradable: bool
    score: float
    tests: list[dict]

@dataclass
class DiffTest:
    name: str
    inpt: str
    outp: str

@dataclass
class SpeedupTest:
    base_time: float
    min_speedup: float
    threads: int = 4
    timeout: int = 120

# Bit masks
COMPILE = 1 << 0
FANALYZE = 1 << 2  
ADDRESSAN = 1 << 3
UNDEFINEDSAN = 1 << 4
THREADSSAN = 1 << 5
SPEEDUP = 1 << 6


class CppGrader:
    def __init__(self, filename, flags = COMPILE, tests = None, speedup = None):
        self.filename : str = filename
        self.flags : int = flags
        self.tests : list[DiffTest] = tests if tests is not None else []
        self.speedup_test : SpeedupTest = speedup 
        
        ## COMPILER FLAGS
        self.gcccompile = [
            'g++', '-fopenmp', '-Wall', '-Wextra', '-Wpedantic', '-Werror',
            '-o', '/grade/student/main', self.filename 
        ]
        self.fanalyzer = [ 
            'g++', '-g', '-fopenmp', '-fanalyzer',
            '-o', '/grade/student/main', self.filename 
        ]

    def strip_whitespaces(self, output):
        return re.sub(r"[^\S\r\n]+", "", output).strip()

    def just_compile(self, fanalyze):
        compilation_options = self.fanalyzer if fanalyze else self.gcccompile
        step = PLTest("Análise Estática", 1) if fanalyze else PLTest("Compilação Simples", 1)
        compilation = subprocess.run(
                 compilation_options,
                 capture_output=True,
                 text=True
                )
        
        step.output = compilation.stderr if compilation.stderr else compilation.stdout
        
        if compilation.returncode == 0:
            step.points = 1
            
        return asdict(step)

    def san_and_run(self, san_type):
        step = PLTest(san_type.capitalize(), 1)
        compilation = subprocess.run(
            ['g++-14', '-no-pie', '-g', '-fopenmp', f'-fsanitize={san_type}',
             '-o', '/grade/student/main', self.filename
             ],
             capture_output=True,
             text=True
            )

        if compilation.returncode != 0:
            step.output = compilation.stderr
            return asdict(step)

        running = subprocess.run(
                ['/grade/student/main'],
                capture_output=True,
                text=True
                )
        
        step.output = f"STDIO:\n\n{running.stdout}\nSTDERR:\n\n{running.stderr}"
        if running.returncode == 0:
            step.points = 1

        return asdict(step)

    def run_tests(self):
        all_steps = []
        
        # Ensure a clean binary is used for logic tests (overriding any sanitizers)
        compilation = subprocess.run(
            self.gcccompile,
            capture_output=True,
            text=True
            )

        if compilation.returncode != 0:
            return all_steps

        for i, test in enumerate(self.tests, start=1):
            step = PLTest(f"{i}: {test.name}", 1)
            try:
                proc = subprocess.run(
                        ['/grade/student/main'], 
                        input=test.inpt,
                        capture_output=True,
                        text=True,
                        timeout=120
                        )
            except subprocess.TimeoutExpired:
                step.output = "Timeout, teste não executou em tempo hábil."
                all_steps.append(asdict(step))
                continue
                        
            stdout = proc.stdout
            clean_out = self.strip_whitespaces(stdout)
            clean_exp = self.strip_whitespaces(test.outp)

            if clean_out == clean_exp:
                step.output = f"\nEsperado:\n{test.outp}"
                step.points = 1
            else:
                l_stdout = stdout.splitlines(keepends=True)
                l_expected = test.outp.splitlines(keepends=True)
                diff = difflib.context_diff(
                        l_expected, 
                        l_stdout, 
                        fromfile="Esperado",
                        tofile="Atual"
                        )

                diff_out = "".join(diff)
                step.output = f"Saída incompatível\n{diff_out}"
            
            all_steps.append(asdict(step))
            
        return all_steps

    def speedup(self):
        """
        Compares the parallel execution time against a TA-defined base time.
        """
        step = PLTest("Avaliação de Speedup", 1)
        
        if self.speedup_test is None:
            step.output = "Erro Interno: Flag SPEEDUP ativada, mas objeto SpeedupTest não foi fornecido."
            return asdict(step)

        # RECOMPILE: We MUST compile a clean, non-sanitized binary before speed measurements.
        # Sanitizers (like thread-sanitizer) add massive overhead and will ruin speedup testing.
        compilation = subprocess.run(self.gcccompile, capture_output=True, text=True)
        if compilation.returncode != 0:
            step.output = "Falha ao compilar binário limpo para teste de speedup."
            return asdict(step)

        if not os.path.isfile('/grade/student/main'):
            step.output = "Binário não encontrado para medir o speedup."
            return asdict(step)

        base_time = self.speedup_test.base_time
        threads = self.speedup_test.threads
        timeout = self.speedup_test.timeout
        min_speedup = self.speedup_test.min_speedup

        # Run Parallel
        start = time.time()
        try:
            par_proc = subprocess.run(
                ['/grade/student/main'], 
                env=dict(os.environ, OMP_NUM_THREADS=str(threads)), 
                capture_output=True,
                text=True,
                timeout=timeout
            )
        except subprocess.TimeoutExpired:
            step.output = f"Timeout: A execução paralela sofreu deadlock ou ultrapassou o limite de {timeout} segundos."
            return asdict(step)
            
        par_time = time.time() - start
        
        if par_proc.returncode != 0:
            step.output = f"Falha na execução durante o teste de speedup (Código {par_proc.returncode}).\nSTDERR:\n{par_proc.stderr}"
            return asdict(step)
            
        if par_time <= 0: 
            par_time = 0.0001
        
        speedup_calc = base_time / par_time
        
        if speedup_calc >= min_speedup:
            step.points = 1
            step.output = (f"Atingiu o speedup esperado.\n"
                           f"Tempo base (Referência): {base_time:.3f}s, "
                           f"Seu tempo ({threads} threads): {par_time:.3f}s.\n"
                           f"Speedup obtido: {speedup_calc:.2f}x (Mínimo exigido: {min_speedup}x)")
        else:
            step.output = (f"Não atingiu o speedup esperado.\n"
                           f"Tempo base (Referência): {base_time:.3f}s, "
                           f"Seu tempo ({threads} threads): {par_time:.3f}s.\n"
                           f"Speedup obtido: {speedup_calc:.2f}x (Mínimo exigido: {min_speedup}x)")
            
        return asdict(step)

    def check_path(self):
        return os.path.isfile(self.filename)

    def run(self):
        all_tests = []
        
        # Guard against missing files
        if not self.check_path():
            step = PLTest("Verificação de Arquivo C++", 1)
            step.output = f"O arquivo {self.filename} não foi encontrado. Você enviou com o nome correto?"
            all_tests.append(asdict(step))
            return all_tests

        if COMPILE & self.flags:
            all_tests.append(self.just_compile(fanalyze=False))
        if FANALYZE & self.flags:
            all_tests.append(self.just_compile(fanalyze=True))
        if ADDRESSAN & self.flags: 
            all_tests.append(self.san_and_run("address"))
        if UNDEFINEDSAN & self.flags: 
            all_tests.append(self.san_and_run("undefined"))
        if THREADSSAN & self.flags: 
            all_tests.append(self.san_and_run("threads"))
        if SPEEDUP & self.flags:
            all_tests.append(self.speedup())
        if self.tests:
            all_tests.extend(self.run_tests())
        
        return all_tests


#####################
# SBATCH EXTRACTOR
#####################

@dataclass
class SbatchTest:
    name : str
    option : str
    value : str

class SbatchGrader:
    def __init__(self, filename, options_tests = None, commands_tests = None):
        self.filename = filename
        self.options = options_tests if options_tests is not None else []
        self.commands = commands_tests if commands_tests is not None else []
        self.shebang = ""
        self.options_to_check = {}
        self.commands_to_check = []

    def check_options(self):
        present = self.options_to_check
        all_steps = []
        for e in self.options:
            step = PLTest(f"SBATCH CHECK: {e.name}", 1)
            option = e.option
            
            if option not in present:
                step.output = f"Diretiva {option} não presente"
            elif present[option] != e.value:
                step.output = f"Diretiva com valor diferente:\nEsperado: {e.value}\nPresente: {present[option]}"
            else:
                step.points = 1
                
            all_steps.append(asdict(step))
            
        return all_steps

    def check_commands(self):
        all_steps = []
        for cmd in self.commands:
            step = PLTest(f"SBATCH CMD: {cmd}", 1)
            
            found = any(cmd in line for line in self.commands_to_check)
            if found:
                step.points = 1
                step.output = f"Comando '{cmd}' encontrado."
            else:
                step.output = f"Comando '{cmd}' ausente do script."
                
            all_steps.append(asdict(step))
            
        return all_steps

    def extract_sbatch(self):
        if not os.path.isfile(self.filename):
            return False

        sbatch_pat = re.compile(r"^#SBATCH\s+(.+)")
        sbatches = {}
        others = []

        with open(self.filename, "r", encoding="utf-8") as f:
            for n, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue 

                if n == 0 and line.startswith("#!"):
                    self.shebang = line 
                    continue

                if line.startswith("#SBATCH"):
                    sb_match = sbatch_pat.match(line)
                    if sb_match:
                        option_str = sb_match.group(1).strip()
                        
                        if "=" in option_str:
                            match = re.match(r"([^=]+)=(\S*)", option_str)
                            name, value = match.groups()
                        else:
                            parts = option_str.split(maxsplit=1)
                            name = parts[0]
                            value = parts[1] if len(parts) > 1 else ""
                            
                        sbatches[name.strip()] = value.strip()

                elif not line.startswith("#"):
                    others.append(line.split("#")[0].strip())

        self.options_to_check = sbatches
        self.commands_to_check = others
        return True

    def run(self): 
        # Guard against missing sbatch files
        if not self.extract_sbatch():
            step = PLTest("Verificação de Arquivo SBATCH", 1)
            step.output = f"O arquivo {self.filename} não foi encontrado."
            return [asdict(step)]

        sb_tests = self.check_options()
        sb_tests.extend(self.check_commands())
        return sb_tests


def grade(graders: list):
    """
    Executes a list of grader objects, aggregates the results, 
    and exports the final valid JSON for PrairieLearn.
    """
    all_tests_results = []

    for grader in graders:
        all_tests_results.extend(grader.run())

    total_points_earned = sum(t['points'] for t in all_tests_results)
    total_max_points = sum(t['max_points'] for t in all_tests_results)

    final_score = (total_points_earned / total_max_points) if total_max_points > 0 else 0.0

    results = PLResult(
        gradable=True, 
        score=final_score, 
        tests=all_tests_results
    )

    write_results(results)

def write_results(results):
    os.makedirs("/grade/results", exist_ok=True)
    with open("/grade/results/results.json", "w", encoding="utf-8") as f:
        json.dump(asdict(results), f, indent=4)

