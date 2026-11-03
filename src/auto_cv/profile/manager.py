# -*- coding: utf-8 -*-
"""
Auto-CV - Profile Manager Module
Version: 1.0.0
Author: Pittaya
License: MIT
Description: CRUD + YAML load/save + validation + interviewer for user profile.
"""

from pathlib import Path
from typing import Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import yaml

from auto_cv.config import get_settings
from auto_cv.profile.schema import (
    Profile,
    PersonalInfo,
    Experience,
    Education,
    Skill,
    Language,
    Preferences,
    ProfileMeta,
    WorkMode,
    JobType,
    LanguageLevel,
    SkillCategory,
    create_default_profile,
    create_minimal_profile,
)


# ============================================================
# RESULT TYPES (SRP - separa responsabilidade de retorno)
# ============================================================

@dataclass
class ValidationResult:
    """Resultado de validação do perfil."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]

    def __bool__(self) -> bool:
        return self.is_valid


@dataclass
class LoadResult:
    """Resultado de carregamento do perfil."""
    profile: Optional[Profile]
    validation: ValidationResult
    file_exists: bool


# ============================================================
# PROFILE MANAGER (Single Responsibility: gerencia persistência)
# ============================================================

class ProfileManager:
    """
    Gerencia persistência e validação do perfil do usuário.

    Single Responsibility: Apenas lida com I/O e validação do Profile.
    Open/Closed: Extensível para novos formatos (JSON, TOML) sem modificar lógica.
    """

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._profile_path = self.settings.profile_path
        self._backup_dir = self.settings.data_dir / "backups" / "profile"

    # ------------------------------------------------------------
    # PATH MANAGEMENT
    # ------------------------------------------------------------

    @property
    def profile_path(self) -> Path:
        """Caminho do arquivo de perfil (computed)."""
        return self._profile_path

    @property
    def backup_dir(self) -> Path:
        """Diretório de backups."""
        return self._backup_dir

    def ensure_directories(self) -> None:
        """Cria diretórios necessários (profile + backups)."""
        self._profile_path.parent.mkdir(parents=True, exist_ok=True)
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        self.settings.ensure_directories()

    # ------------------------------------------------------------
    # LOAD / SAVE (Core CRUD)
    # ------------------------------------------------------------

    def load_profile(self, validate: bool = True) -> LoadResult:
        """
        Carrega perfil do arquivo YAML.

        Args:
            validate: Se True, valida o perfil após carregar.

        Returns:
            LoadResult com profile, validation e file_exists.
        """
        self.ensure_directories()

        if not self._profile_path.exists():
            return LoadResult(
                profile=None,
                validation=ValidationResult(True, [], ["Arquivo de perfil não encontrado"]),
                file_exists=False,
            )

        try:
            with open(self._profile_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            profile = Profile.from_yaml_dict(data)

            validation = ValidationResult(True, [], [])
            if validate:
                validation = self.validate_profile(profile)

            return LoadResult(
                profile=profile,
                validation=validation,
                file_exists=True,
            )

        except yaml.YAMLError as e:
            return LoadResult(
                profile=None,
                validation=ValidationResult(False, [f"YAML inválido: {e}"], []),
                file_exists=True,
            )
        except Exception as e:
            return LoadResult(
                profile=None,
                validation=ValidationResult(False, [f"Erro ao carregar perfil: {e}"], []),
                file_exists=True,
            )

    def save_profile(self, profile: Profile, backup: bool = True) -> ValidationResult:
        """
        Salva perfil no arquivo YAML com backup atômico.

        Args:
            profile: Profile a salvar.
            backup: Se True, cria backup antes de sobrescrever.

        Returns:
            ValidationResult indicando sucesso/falha.
        """
        self.ensure_directories()

        # Atualiza timestamp antes de salvar
        self.update_timestamp(profile)

        # Valida antes de salvar
        validation = self.validate_profile(profile)
        if not validation.is_valid:
            return validation

        # Backup do arquivo atual
        if backup and self._profile_path.exists():
            self._create_backup()

        # Escrita atômica: escreve em temp + rename
        temp_path = self._profile_path.with_suffix(".yaml.tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    profile.to_yaml_dict(),
                    f,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                )
            temp_path.replace(self._profile_path)
            return ValidationResult(True, [], ["Perfil salvo com sucesso"])

        except Exception as e:
            # Limpa temp se falhou
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
            return ValidationResult(False, [f"Erro ao salvar perfil: {e}"], [])

    def _create_backup(self) -> None:
        """Cria backup timestampado do perfil atual."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"profile_{timestamp}.yaml"
        backup_path = self._backup_dir / backup_name

        try:
            import shutil
            shutil.copy2(self._profile_path, backup_path)
            # Mantém só últimos 10 backups
            self._prune_backups(keep=10)
        except Exception:
            # Backup é best-effort, não falha o save
            pass

    def _prune_backups(self, keep: int = 10) -> None:
        """Remove backups antigos mantendo os N mais recentes."""
        backups = sorted(self._backup_dir.glob("profile_*.yaml"), key=lambda p: p.stat().st_mtime)
        for old in backups[:-keep]:
            old.unlink(missing_ok=True)

    # ------------------------------------------------------------
    # DEFAULT / ENSURE
    # ------------------------------------------------------------

    def create_default(self, minimal: bool = False) -> Profile:
        """
        Cria perfil padrão (template completo ou mínimo).

        Args:
            minimal: Se True, cria perfil mínimo (apenas obrigatórios).

        Returns:
            Profile criado (não salvo automaticamente).
        """
        if minimal:
            return create_minimal_profile(
                name="Seu Nome",
                email="seu@email.com",
                location="São Paulo, SP, Brasil",
            )
        return create_default_profile()

    def ensure_profile(self, minimal: bool = False) -> LoadResult:
        """
        Garante que existe um perfil: carrega se existe, cria default se não.

        Args:
            minimal: Se criar, usar template mínimo.

        Returns:
            LoadResult do perfil (criado ou carregado).
        """
        result = self.load_profile(validate=True)

        if result.profile is None:
            # Cria e salva default
            profile = self.create_default(minimal=minimal)
            save_result = self.save_profile(profile, backup=False)
            if not save_result.is_valid:
                return LoadResult(
                    profile=None,
                    validation=save_result,
                    file_exists=False,
                )
            return LoadResult(
                profile=profile,
                validation=ValidationResult(True, [], ["Perfil padrão criado"]),
                file_exists=True,
            )

        return result

    # ------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------

    def validate_profile(self, profile: Profile) -> ValidationResult:
        """
        Valida perfil completo (estrutura + regras de negócio).

        Returns:
            ValidationResult com errors (bloqueantes) e warnings (alertas).
        """
        errors: List[str] = []
        warnings: List[str] = []

        # --- Validações estruturais (Pydantic já faz a maior parte) ---
        try:
            # Força re-validação completa
            Profile.model_validate(profile.model_dump())
        except Exception as e:
            errors.append(f"Estrutura inválida: {e}")

        # --- Regras de negócio customizadas ---
        # Personal info
        if not profile.personal.name or profile.personal.name == "Seu Nome":
            warnings.append("Nome parece ser placeholder")
        if not profile.personal.email or profile.personal.email == "seu@email.com":
            warnings.append("Email parece ser placeholder")
        if not profile.personal.linkedin:
            warnings.append("LinkedIn não preenchido (recomendado para matching)")
        if not profile.personal.github:
            warnings.append("GitHub não preenchido (recomendado para devs)")
        if not profile.personal.summary:
            warnings.append("Resumo profissional vazio (usado no CV)")

        # Experience + Education (schema exige pelo menos um dos dois)
        if not profile.experience and not profile.education:
            errors.append("Nenhuma experiência profissional NEM formação acadêmica")
        else:
            if not profile.experience:
                warnings.append("Nenhuma experiência profissional (apenas formação)")
            else:
                current_jobs = [e for e in profile.experience if e.is_current]
                if len(current_jobs) > 1:
                    warnings.append(f"Múltiplos empregos atuais ({len(current_jobs)})")
                elif len(current_jobs) == 0:
                    warnings.append("Nenhum emprego atual marcado")

                for i, exp in enumerate(profile.experience):
                    if not exp.achievements:
                        warnings.append(f"Experiência {i+1} ({exp.role}): sem realizações mensuráveis")
                    if not exp.technologies:
                        warnings.append(f"Experiência {i+1} ({exp.role}): sem tecnologias listadas")

            if not profile.education:
                warnings.append("Nenhuma formação acadêmica (apenas experiência)")

        # Skills
        if not profile.skills:
            errors.append("Nenhuma skill cadastrada")
        else:
            categories_present = {s.category for s in profile.skills}
            if SkillCategory.LANGUAGES not in categories_present:
                warnings.append("Nenhuma linguagem de programação (category=LANGUAGES)")
            if len(profile.skills) < 5:
                warnings.append("Poucas skills (recomendado 10+ para bom matching)")

        # Languages
        if not profile.languages:
            errors.append("Nenhum idioma cadastrado")
        else:
            has_portuguese = any(l.language.lower() in {"português", "portugues", "pt"} for l in profile.languages)
            has_english = any(l.language.lower() in {"inglês", "ingles", "en", "english"} for l in profile.languages)
            if not has_portuguese:
                warnings.append("Português não listado (assumido nativo)")
            if not has_english:
                warnings.append("Inglês não listado (recomendado para vagas globais)")

        # Preferences
        if not profile.preferences.keywords_include:
            warnings.append("Nenhuma keyword de inclusão (matching será fraco)")
        if not profile.preferences.locations:
            warnings.append("Nenhuma localização preferida")

        # Meta
        if profile.meta.version < 1:
            warnings.append("Versão do schema antiga, considere migrar")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ------------------------------------------------------------
    # UTILITIES
    # ------------------------------------------------------------

    def update_timestamp(self, profile: Profile) -> None:
        """Atualiza meta.updated_at para agora."""
        profile.meta.updated_at = datetime.now()
        profile.meta.version += 1

    def backup_profile(self) -> Optional[Path]:
        """Cria backup manual do perfil atual. Retorna path do backup ou None."""
        if not self._profile_path.exists():
            return None
        self._create_backup()
        backups = sorted(self._backup_dir.glob("profile_*.yaml"), key=lambda p: p.stat().st_mtime)
        return backups[-1] if backups else None

    def list_backups(self) -> List[Path]:
        """Lista backups disponíveis (mais recente primeiro)."""
        return sorted(self._backup_dir.glob("profile_*.yaml"), key=lambda p: p.stat().st_mtime, reverse=True)

    def restore_backup(self, backup_path: Path) -> ValidationResult:
        """Restaura perfil a partir de um backup."""
        if not backup_path.exists():
            return ValidationResult(False, ["Backup não encontrado"], [])

        try:
            import shutil
            shutil.copy2(backup_path, self._profile_path)
            return ValidationResult(True, [], [f"Perfil restaurado de {backup_path.name}"])
        except Exception as e:
            return ValidationResult(False, [f"Erro ao restaurar: {e}"], [])


# ============================================================
# INTERACTIVE INTERVIEWER (Optional - para setup inicial)
# ============================================================

class ProfileInterviewer:
    """
    Entrevista interativa para preencher perfil (CLI wizard).

    Single Responsibility: Coleta dados do usuário via prompts.
    Open/Closed: Fácil adicionar novos campos/perguntas.
    """

    def __init__(self, manager: ProfileManager):
        self.manager = manager

    def run_interview(self, profile: Optional[Profile] = None) -> Profile:
        """
        Executa entrevista completa e retorna Profile preenchido.

        Args:
            profile: Profile base para editar (None = cria do zero).

        Returns:
            Profile preenchido (não salvo automaticamente).
        """
        from rich.prompt import Prompt, Confirm, IntPrompt
        from rich.console import Console

        console = Console()
        profile = profile or self.manager.create_default(minimal=True)

        console.rule("[bold cyan]Auto-CV - Entrevista de Perfil[/bold cyan]")
        console.print("Vamos configurar seu perfil. Pressione Enter para manter o valor atual.\n")

        # Personal Info
        profile.personal = self._interview_personal(profile.personal, console)

        # Experience
        profile.experience = self._interview_experience(profile.experience, console)

        # Education
        profile.education = self._interview_education(profile.education, console)

        # Skills
        profile.skills = self._interview_skills(profile.skills, console)

        # Languages
        profile.languages = self._interview_languages(profile.languages, console)

        # Preferences
        profile.preferences = self._interview_preferences(profile.preferences, console)

        console.print("\n[green]✓[/green] Entrevista concluída!")
        return profile

    def _interview_personal(self, current: PersonalInfo, console) -> PersonalInfo:
        console.rule("[bold]Informações Pessoais[/bold]")
        return PersonalInfo(
            name=Prompt.ask("Nome completo", default=current.name),
            email=Prompt.ask("Email", default=current.email),
            phone=Prompt.ask("Telefone (com DDD)", default=current.phone or ""),
            location=Prompt.ask("Cidade, Estado, País", default=current.location),
            linkedin=Prompt.ask("LinkedIn URL", default=str(current.linkedin) if current.linkedin else ""),
            github=Prompt.ask("GitHub URL", default=str(current.github) if current.github else ""),
            portfolio=Prompt.ask("Portfolio/Site", default=str(current.portfolio) if current.portfolio else ""),
            summary=Prompt.ask("Resumo profissional (2-3 linhas)", default=current.summary),
        )

    def _interview_experience(self, current: List[Experience], console) -> List[Experience]:
        console.rule("[bold]Experiência Profissional[/bold]")
        experiences = list(current)

        while True:
            if experiences:
                console.print("\nExperiências atuais:")
                for i, exp in enumerate(experiences):
                    status = "🟢 Atual" if exp.is_current else f"🔴 {exp.end_date}"
                    console.print(f"  {i+1}. {exp.role} @ {exp.company} ({status})")

            if not Confirm.ask("\nAdicionar/editar experiência?", default=not experiences):
                break

            idx = None
            if experiences and Confirm.ask("Editar existente?", default=False):
                idx = IntPrompt.ask("Número", default=1) - 1
                if idx < 0 or idx >= len(experiences):
                    console.print("[red]Índice inválido[/red]")
                    continue
                base = experiences[idx]
            else:
                base = None
                idx = len(experiences)

            exp = self._prompt_experience(base, console)
            if idx < len(experiences):
                experiences[idx] = exp
            else:
                experiences.append(exp)

        return experiences

    def _prompt_experience(self, base: Optional[Experience], console) -> Experience:
        from datetime import date
        from rich.prompt import Prompt

        console.print("  --- Nova Experiência ---")
        company = Prompt.ask("Empresa", default=base.company if base else "")
        role = Prompt.ask("Cargo", default=base.role if base else "")
        start = Prompt.ask("Início (YYYY-MM-DD)", default=base.start_date.isoformat() if base else str(date.today().replace(year=date.today().year-2)))
        end_str = Prompt.ask("Fim (YYYY-MM-DD ou vazio=atual)", default=base.end_date.isoformat() if base and base.end_date else "")
        location = Prompt.ask("Localização", default=base.location if base else "")
        work_mode = Prompt.ask("Modalidade (remote/hybrid/onsite)", default=base.work_mode.value if base else "remote")
        description = Prompt.ask("Descrição", default=base.description if base else "")

        achievements = []
        if base and base.achievements:
            console.print("  Realizações atuais (Enter para manter, 'add' para adicionar, 'del' para remover):")
            for a in base.achievements:
                console.print(f"    - {a}")
        while True:
            ach = Prompt.ask("  Realização (vazio para parar)", default="")
            if not ach:
                break
            achievements.append(ach)

        technologies = []
        if base and base.technologies:
            tech_str = Prompt.ask("Tecnologias (separadas por vírgula)", default=", ".join(base.technologies))
            technologies = [t.strip() for t in tech_str.split(",") if t.strip()]

        return Experience(
            company=company,
            role=role,
            start_date=date.fromisoformat(start),
            end_date=date.fromisoformat(end_str) if end_str else None,
            location=location,
            work_mode=WorkMode(work_mode),
            description=description,
            achievements=achievements,
            technologies=technologies,
        )

    def _interview_education(self, current: List[Education], console) -> List[Education]:
        console.rule("[bold]Formação Acadêmica[/bold]")
        educations = list(current)

        while True:
            if educations:
                console.print("\nFormações atuais:")
                for i, edu in enumerate(educations):
                    status = "🟢 Cursando" if edu.is_current else f"🔴 Concluído {edu.end_date}"
                    console.print(f"  {i+1}. {edu.degree} @ {edu.institution} ({status})")

            if not Confirm.ask("\nAdicionar/editar formação?", default=not educations):
                break

            idx = None
            if educations and Confirm.ask("Editar existente?", default=False):
                idx = IntPrompt.ask("Número", default=1) - 1
                if idx < 0 or idx >= len(educations):
                    console.print("[red]Índice inválido[/red]")
                    continue
                base = educations[idx]
            else:
                base = None
                idx = len(educations)

            edu = self._prompt_education(base, console)
            if idx < len(educations):
                educations[idx] = edu
            else:
                educations.append(edu)

        return educations

    def _prompt_education(self, base: Optional[Education], console) -> Education:
        from datetime import date
        from rich.prompt import Prompt

        console.print("  --- Nova Formação ---")
        institution = Prompt.ask("Instituição", default=base.institution if base else "")
        degree = Prompt.ask("Curso/Grau", default=base.degree if base else "")
        field = Prompt.ask("Área de estudo", default=base.field_of_study if base else "")
        start = Prompt.ask("Início (YYYY-MM-DD)", default=base.start_date.isoformat() if base else str(date.today().replace(year=date.today().year-4)))
        end_str = Prompt.ask("Conclusão (YYYY-MM-DD ou vazio=cursando)", default=base.end_date.isoformat() if base and base.end_date else "")

        highlights = []
        if base and base.highlights:
            for h in base.highlights:
                console.print(f"    - {h}")
        while True:
            h = Prompt.ask("  Destaque (vazio para parar)", default="")
            if not h:
                break
            highlights.append(h)

        return Education(
            institution=institution,
            degree=degree,
            field_of_study=field if field else None,
            start_date=date.fromisoformat(start),
            end_date=date.fromisoformat(end_str) if end_str else None,
            highlights=highlights,
        )

    def _interview_skills(self, current: List[Skill], console) -> List[Skill]:
        console.rule("[bold]Skills[/bold]")
        skills = list(current)

        # Agrupa por categoria para exibir
        by_cat = {}
        for s in skills:
            by_cat.setdefault(s.category, []).append(s)

        for cat in SkillCategory:
            items = by_cat.get(cat, [])
            if items:
                console.print(f"\n  {cat.value}: {', '.join(s.name for s in items)}")

        while True:
            if not Confirm.ask("\nAdicionar skill?", default=False):
                break

            cat_str = Prompt.ask("Categoria (languages/frameworks/infrastructure/databases/tools/soft_skills/other)", default="languages")
            try:
                cat = SkillCategory(cat_str)
            except ValueError:
                console.print("[red]Categoria inválida[/red]")
                continue

            name = Prompt.ask("Nome da skill", default="")
            if not name:
                continue

            level_str = Prompt.ask("Nível 1-5 (opcional)", default="")
            level = int(level_str) if level_str.isdigit() and 1 <= int(level_str) <= 5 else None

            years_str = Prompt.ask("Anos de experiência (opcional)", default="")
            years = float(years_str) if years_str.replace(".", "").isdigit() else None

            skills.append(Skill(category=cat, name=name, level=level, years_experience=years))

        return skills

    def _interview_languages(self, current: List[Language], console) -> List[Language]:
        console.rule("[bold]Idiomas[/bold]")
        languages = list(current)

        for lang in languages:
            console.print(f"  - {lang.language}: {lang.level.value} {'✓' if lang.certified else ''}")

        while True:
            if not Confirm.ask("\nAdicionar idioma?", default=not languages):
                break

            name = Prompt.ask("Idioma", default="")
            if not name:
                continue

            level_str = Prompt.ask("Nível (Nativo/C2/C1/B2/B1/A2/A1)", default="B2")
            try:
                level = LanguageLevel(level_str)
            except ValueError:
                console.print("[red]Nível inválido, usando B2[/red]")
                level = LanguageLevel.B2

            certified = Confirm.ask("Possui certificação?", default=False)

            languages.append(Language(language=name, level=level, certified=certified))

        return languages

    def _interview_preferences(self, current: Preferences, console) -> Preferences:
        console.rule("[bold]Preferências de Busca[/bold]")

        # Job types
        job_types = current.job_types
        console.print(f"Tipos: {[j.value for j in job_types]}")
        if Confirm.ask("Editar tipos de vaga?", default=False):
            job_types = []
            for jt in JobType:
                if Confirm.ask(f"  {jt.value}?", default=jt in current.job_types):
                    job_types.append(jt)

        # Work modes
        work_modes = current.work_modes
        console.print(f"Modalidades: {[w.value for w in work_modes]}")
        if Confirm.ask("Editar modalidades?", default=False):
            work_modes = []
            for wm in WorkMode:
                if Confirm.ask(f"  {wm.value}?", default=wm in current.work_modes):
                    work_modes.append(wm)

        # Locations
        locations = current.locations
        console.print(f"Localizações: {locations}")
        if Confirm.ask("Editar localizações?", default=False):
            loc_str = Prompt.ask("Localizações (separadas por vírgula)", default=", ".join(locations))
            locations = [l.strip() for l in loc_str.split(",") if l.strip()]

        # Salary
        salary_brl = current.salary_min_brl
        if Confirm.ask("Definir salário mínimo BRL?", default=salary_brl is not None):
            sal_str = Prompt.ask("Valor (BRL/mês)", default=str(salary_brl) if salary_brl else "")
            salary_brl = int(sal_str) if sal_str.isdigit() else None

        salary_usd = current.salary_min_usd
        if Confirm.ask("Definir salário mínimo USD?", default=salary_usd is not None):
            sal_str = Prompt.ask("Valor (USD/mês)", default=str(salary_usd) if salary_usd else "")
            salary_usd = int(sal_str) if sal_str.isdigit() else None

        # Keywords
        kw_include = current.keywords_include
        console.print(f"Keywords include: {kw_include[:5]}...")
        if Confirm.ask("Editar keywords inclusão?", default=False):
            kw_str = Prompt.ask("Keywords (vírgula)", default=", ".join(kw_include))
            kw_include = [k.strip() for k in kw_str.split(",") if k.strip()]

        kw_exclude = current.keywords_exclude
        console.print(f"Keywords exclude: {kw_exclude[:5]}...")
        if Confirm.ask("Editar keywords exclusão?", default=False):
            kw_str = Prompt.ask("Keywords (vírgula)", default=", ".join(kw_exclude))
            kw_exclude = [k.strip() for k in kw_str.split(",") if k.strip()]

        return Preferences(
            job_types=job_types,
            work_modes=work_modes,
            locations=locations,
            exclude_locations=current.exclude_locations,
            salary_min_brl=salary_brl,
            salary_min_usd=salary_usd,
            salary_negotiable=current.salary_negotiable,
            keywords_include=kw_include,
            keywords_exclude=kw_exclude,
            companies_exclude=current.companies_exclude,
            companies_prefer=current.companies_prefer,
            visa_sponsorship=current.visa_sponsorship,
            remote_ok_anywhere=current.remote_ok_anywhere,
            notice_period_days=current.notice_period_days,
        )


# ============================================================
# CONVENIENCE FUNCTIONS (Module-level API)
# ============================================================

def get_manager() -> ProfileManager:
    """Retorna instância singleton do manager."""
    return ProfileManager()


def load_profile(validate: bool = True) -> LoadResult:
    """Carrega perfil (função conveniência)."""
    return get_manager().load_profile(validate=validate)


def save_profile(profile: Profile, backup: bool = True) -> ValidationResult:
    """Salva perfil (função conveniência)."""
    return get_manager().save_profile(profile, backup=backup)


def ensure_profile(minimal: bool = False) -> LoadResult:
    """Garante perfil existente (função conveniência)."""
    return get_manager().ensure_profile(minimal=minimal)


def validate_profile(profile: Profile) -> ValidationResult:
    """Valida perfil (função conveniência)."""
    return get_manager().validate_profile(profile)


def interview_profile(profile: Optional[Profile] = None) -> Profile:
    """Executa entrevista interativa (função conveniência)."""
    return ProfileInterviewer(get_manager()).run_interview(profile)