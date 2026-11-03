# -*- coding: utf-8 -*-
"""
Auto-CV - Profile Schema Module
Version: 1.0.0
Author: Auto-CV Team
License: MIT
Description: Pydantic models for user profile (PersonalInfo, Experience, Education, Skills, Preferences, Profile).
"""

from datetime import date, datetime
from typing import Optional, List
from enum import Enum
from pydantic import BaseModel, Field, EmailStr, HttpUrl, field_validator, model_validator, computed_field


# ============================================================
# ENUMS (Open/Closed - fácil estender sem modificar)
# ============================================================

class WorkMode(str, Enum):
    """Modalidades de trabalho."""
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"


class JobType(str, Enum):
    """Tipos de contrato."""
    FULL_TIME = "full-time"
    PART_TIME = "part-time"
    CONTRACT = "contract"
    INTERNSHIP = "internship"
    FREELANCE = "freelance"


class LanguageLevel(str, Enum):
    """Níveis de proficiência (CEFR)."""
    NATIVE = "Nativo"
    C2 = "C2 (Proficiente)"
    C1 = "C1 (Avançado)"
    B2 = "B2 (Intermediário Alto)"
    B1 = "B1 (Intermediário)"
    A2 = "A2 (Básico)"
    A1 = "A1 (Iniciante)"


class SkillCategory(str, Enum):
    """Categorias de skills (extensível via OCP)."""
    LANGUAGES = "languages"
    FRAMEWORKS = "frameworks"
    INFRASTRUCTURE = "infrastructure"
    DATABASES = "databases"
    TOOLS = "tools"
    SOFT_SKILLS = "soft_skills"
    OTHER = "other"


# ============================================================
# CORE MODELS (Single Responsibility - cada modelo uma responsabilidade)
# ============================================================

class PersonalInfo(BaseModel):
    """Informações pessoais e de contato."""

    name: str = Field(..., min_length=1, description="Nome completo")
    email: EmailStr = Field(..., description="Email principal")
    phone: Optional[str] = Field(default=None, description="Telefone com DDD")
    location: str = Field(..., min_length=1, description="Cidade, Estado, País")
    linkedin: Optional[HttpUrl] = Field(default=None, description="URL do LinkedIn")
    github: Optional[HttpUrl] = Field(default=None, description="URL do GitHub")
    portfolio: Optional[HttpUrl] = Field(default=None, description="Portfolio/Site pessoal")
    summary: str = Field(default="", max_length=500, description="Resumo profissional (2-3 linhas)")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and not any(c.isdigit() for c in v):
            raise ValueError("Telefone deve conter dígitos")
        return v


class Experience(BaseModel):
    """Experiência profissional."""

    company: str = Field(..., min_length=1, description="Nome da empresa")
    role: str = Field(..., min_length=1, description="Cargo/Título")
    start_date: date = Field(..., description="Data de início")
    end_date: Optional[date] = Field(default=None, description="Data de fim (None = atual)")
    location: str = Field(default="", description="Localização (cidade, país)")
    work_mode: WorkMode = Field(default=WorkMode.HYBRID, description="Modalidade de trabalho")
    description: str = Field(default="", description="Descrição geral do papel")
    achievements: List[str] = Field(default_factory=list, description="Realizações mensuráveis")
    technologies: List[str] = Field(default_factory=list, description="Tecnologias usadas")

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: Optional[date], info) -> Optional[date]:
        if v and info.data.get("start_date") and v < info.data["start_date"]:
            raise ValueError("Data de fim deve ser posterior à data de início")
        return v

    @computed_field
    @property
    def is_current(self) -> bool:
        """Se é emprego atual."""
        return self.end_date is None

    @computed_field
    @property
    def duration_months(self) -> int:
        """Duração em meses."""
        end = self.end_date or date.today()
        delta = end - self.start_date
        return max(1, round(delta.days / 30.44))


class Education(BaseModel):
    """Formação acadêmica."""

    institution: str = Field(..., min_length=1, description="Instituição")
    degree: str = Field(..., min_length=1, description="Curso/Grau")
    field_of_study: Optional[str] = Field(default=None, description="Área de estudo")
    start_date: date = Field(..., description="Data de início")
    end_date: Optional[date] = Field(default=None, description="Data de conclusão (None = cursando)")
    gpa: Optional[str] = Field(default=None, description="Notas/Créditos (opcional)")
    highlights: List[str] = Field(default_factory=list, description="Destaques: projetos, prêmios, etc.")

    @field_validator("end_date")
    @classmethod
    def validate_dates(cls, v: Optional[date], info) -> Optional[date]:
        if v and info.data.get("start_date") and v < info.data["start_date"]:
            raise ValueError("Data de fim deve ser posterior à data de início")
        return v

    @computed_field
    @property
    def is_current(self) -> bool:
        return self.end_date is None


class Skill(BaseModel):
    """Skill individual agrupada por categoria."""

    category: SkillCategory = Field(..., description="Categoria da skill")
    name: str = Field(..., min_length=1, description="Nome da skill/tecnologia")
    level: Optional[int] = Field(default=None, ge=1, le=5, description="Nível 1-5 (opcional)")
    years_experience: Optional[float] = Field(default=None, ge=0, description="Anos de experiência")


class Language(BaseModel):
    """Idioma e proficiência."""

    language: str = Field(..., min_length=1, description="Nome do idioma")
    level: LanguageLevel = Field(default=LanguageLevel.B2, description="Nível CEFR")
    certified: bool = Field(default=False, description="Possui certificação oficial")


class Preferences(BaseModel):
    """Preferências de busca de vagas."""

    # Tipos de vaga
    job_types: List[JobType] = Field(
        default_factory=lambda: [JobType.FULL_TIME, JobType.CONTRACT],
        description="Tipos de contrato desejados",
    )
    work_modes: List[WorkMode] = Field(
        default_factory=lambda: [WorkMode.REMOTE, WorkMode.HYBRID],
        description="Modalidades de trabalho aceitas",
    )

    # Localização
    locations: List[str] = Field(
        default_factory=lambda: ["Brasil", "Remote Global", "Portugal", "Alemanha"],
        description="Localizações desejadas (países, cidades, 'Remote Global')",
    )
    exclude_locations: List[str] = Field(
        default_factory=list,
        description="Localizações a excluir",
    )

    # Salário
    salary_min_brl: Optional[int] = Field(default=None, ge=0, description="Salário mínimo (BRL/mês)")
    salary_min_usd: Optional[int] = Field(default=None, ge=0, description="Salário mínimo (USD/mês)")
    salary_negotiable: bool = Field(default=True, description="Aceita negociar")

    # Keywords
    keywords_include: List[str] = Field(
        default_factory=lambda: ["backend", "api", "cloud", "architect", "lead", "senior", "python", "aws", "kubernetes"],
        description="Palavras-chave que DEVEM aparecer na vaga",
    )
    keywords_exclude: List[str] = Field(
        default_factory=lambda: ["frontend-only", "php", "wordpress", "sales", "support", "estágio", "júnior"],
        description="Palavras-chave que NÃO devem aparecer na vaga",
    )

    # Empresas
    companies_exclude: List[str] = Field(
        default_factory=list,
        description="Empresas para ignorar (blacklist)",
    )
    companies_prefer: List[str] = Field(
        default_factory=list,
        description="Empresas preferidas (boost no score)",
    )

    # Outros
    visa_sponsorship: bool = Field(default=False, description="Precisa de patrocínio de visto")
    remote_ok_anywhere: bool = Field(default=True, description="Aceita remote de qualquer lugar")
    notice_period_days: Optional[int] = Field(default=None, ge=0, description="Período de aviso prévio (dias)")


# ============================================================
# METADATA (Internal - não vem do usuário)
# ============================================================

class ProfileMeta(BaseModel):
    """Metadados internos do perfil."""

    created_at: datetime = Field(default_factory=datetime.now, description="Criação do perfil")
    updated_at: datetime = Field(default_factory=datetime.now, description="Última atualização")
    version: int = Field(default=1, ge=1, description="Versão do schema do perfil")
    source: str = Field(default="manual", description="Origem: manual, import, interview")


# ============================================================
# ROOT MODEL - Profile (Aggregate Root)
# ============================================================

class Profile(BaseModel):
    """
    Perfil completo do usuário (Aggregate Root).

    Single Responsibility: Agrega todas as entidades do perfil.
    Open/Closed: Extensível via novos campos sem quebrar existentes.
    """

    personal: PersonalInfo = Field(..., description="Informações pessoais")
    experience: List[Experience] = Field(default_factory=list, description="Experiências profissionais")
    education: List[Education] = Field(default_factory=list, description="Formação acadêmica")
    skills: List[Skill] = Field(default_factory=list, description="Skills técnicas e soft skills")
    languages: List[Language] = Field(default_factory=list, description="Idiomas")
    preferences: Preferences = Field(default_factory=Preferences, description="Preferências de busca")
    meta: ProfileMeta = Field(default_factory=ProfileMeta, description="Metadados internos")

    # ============================================================
    # VALIDAÇÕES CRUZADAS (Model-level)
    # ============================================================

    @model_validator(mode="after")
    def validate_profile(self) -> "Profile":
        """Validações que dependem de múltiplos campos."""
        # Pelo menos uma experiência ou educação
        if not self.experience and not self.education:
            raise ValueError("Perfil deve ter ao menos uma experiência OU formação")

        # Pelo menos uma skill
        if not self.skills:
            raise ValueError("Perfil deve ter ao menos uma skill")

        # Pelo menos um idioma
        if not self.languages:
            raise ValueError("Perfil deve ter ao menos um idioma")

        # Atualizar timestamp
        self.meta.updated_at = datetime.now()

        return self

    # ============================================================
    # COMPUTED FIELDS (Derived data - OCP)
    # ============================================================

    @computed_field
    @property
    def total_experience_years(self) -> float:
        """Total de anos de experiência profissional."""
        return sum(exp.duration_months for exp in self.experience) / 12

    @computed_field
    @property
    def current_role(self) -> Optional[str]:
        """Cargo atual (experiência mais recente sem end_date)."""
        current = [e for e in self.experience if e.is_current]
        return current[0].role if current else None

    @computed_field
    @property
    def current_company(self) -> Optional[str]:
        """Empresa atual."""
        current = [e for e in self.experience if e.is_current]
        return current[0].company if current else None

    @computed_field
    @property
    def top_skills(self) -> List[str]:
        """Top 10 skills por categoria (para matching rápido)."""
        # Prioriza: languages > frameworks > infrastructure > databases > tools > other
        priority = {
            SkillCategory.LANGUAGES: 0,
            SkillCategory.FRAMEWORKS: 1,
            SkillCategory.INFRASTRUCTURE: 2,
            SkillCategory.DATABASES: 3,
            SkillCategory.TOOLS: 4,
            SkillCategory.SOFT_SKILLS: 5,
            SkillCategory.OTHER: 6,
        }
        sorted_skills = sorted(self.skills, key=lambda s: priority.get(s.category, 99))
        return [s.name for s in sorted_skills[:10]]

    @computed_field
    @property
    def skill_keywords(self) -> List[str]:
        """Todas as skills como keywords para matching (lowercase)."""
        return [s.name.lower() for s in self.skills]

    @computed_field
    @property
    def preferred_locations_normalized(self) -> List[str]:
        """Localizações normalizadas para busca."""
        return [loc.lower().strip() for loc in self.preferences.locations]

    @computed_field
    @property
    def is_senior_level(self) -> bool:
        """Heurística: 5+ anos exp OU cargo lead/architect/senior."""
        if self.total_experience_years >= 5:
            return True
        senior_keywords = {"lead", "architect", "senior", "principal", "staff", "manager", "head"}
        current = (self.current_role or "").lower()
        return any(kw in current for kw in senior_keywords)

    # ============================================================
    # SERIALIZAÇÃO (Para YAML/JSON)
    # ============================================================

    def to_yaml_dict(self) -> dict:
        """Converte para dict compatível com YAML (dates → strings)."""
        data = self.model_dump(mode="json")
        # Converter dates para strings ISO
        for exp in data.get("experience", []):
            exp["start_date"] = exp["start_date"]
            if exp.get("end_date"):
                exp["end_date"] = exp["end_date"]
        for edu in data.get("education", []):
            edu["start_date"] = edu["start_date"]
            if edu.get("end_date"):
                edu["end_date"] = edu["end_date"]
        return data

    @classmethod
    def from_yaml_dict(cls, data: dict) -> "Profile":
        """Cria Profile a partir de dict YAML (strings → dates)."""
        # Pydantic v2 faz parsing automático de strings ISO para date
        return cls.model_validate(data)


# ============================================================
# FACTORY / BUILDER (OCP - fácil criar perfis de teste/default)
# ============================================================

def create_default_profile() -> Profile:
    """Cria perfil padrão vazio (para template)."""
    return Profile(
        personal=PersonalInfo(
            name="Seu Nome",
            email="seu@email.com",
            phone="+55 11 99999-9999",
            location="São Paulo, SP, Brasil",
            linkedin="https://linkedin.com/in/seuusuario",
            github="https://github.com/seuusuario",
            portfolio="https://seuportfolio.com",
            summary="Resumo profissional 2-3 linhas...",
        ),
        experience=[
            Experience(
                company="Empresa Atual",
                role="Senior Software Engineer",
                start_date=date(2022, 1, 1),
                end_date=None,
                location="São Paulo, SP (Remote)",
                work_mode=WorkMode.REMOTE,
                description="Liderança técnica de...",
                achievements=[
                    "Reduziu latência em 40%...",
                    "Mentorou 5 engenheiros...",
                ],
                technologies=["Python", "PostgreSQL", "AWS", "Kubernetes", "React"],
            )
        ],
        education=[
            Education(
                institution="Universidade X",
                degree="Bacharelado em Ciência da Computação",
                start_date=date(2016, 1, 1),
                end_date=date(2020, 12, 1),
                highlights=["Iniciação Científica", "Monitoria"],
            )
        ],
        skills=[
            # Languages
            Skill(category=SkillCategory.LANGUAGES, name="Python", level=5, years_experience=8),
            Skill(category=SkillCategory.LANGUAGES, name="TypeScript", level=4, years_experience=5),
            Skill(category=SkillCategory.LANGUAGES, name="Go", level=3, years_experience=2),
            Skill(category=SkillCategory.LANGUAGES, name="SQL", level=5, years_experience=8),
            Skill(category=SkillCategory.LANGUAGES, name="Rust", level=2, years_experience=1),
            # Frameworks
            Skill(category=SkillCategory.FRAMEWORKS, name="FastAPI", level=5, years_experience=4),
            Skill(category=SkillCategory.FRAMEWORKS, name="React", level=4, years_experience=5),
            Skill(category=SkillCategory.FRAMEWORKS, name="Next.js", level=3, years_experience=2),
            Skill(category=SkillCategory.FRAMEWORKS, name="Django", level=3, years_experience=3),
            # Infrastructure
            Skill(category=SkillCategory.INFRASTRUCTURE, name="AWS", level=5, years_experience=6),
            Skill(category=SkillCategory.INFRASTRUCTURE, name="Docker", level=5, years_experience=6),
            Skill(category=SkillCategory.INFRASTRUCTURE, name="Kubernetes", level=4, years_experience=4),
            Skill(category=SkillCategory.INFRASTRUCTURE, name="Terraform", level=4, years_experience=3),
            Skill(category=SkillCategory.INFRASTRUCTURE, name="GitHub Actions", level=5, years_experience=5),
            # Databases
            Skill(category=SkillCategory.DATABASES, name="PostgreSQL", level=5, years_experience=7),
            Skill(category=SkillCategory.DATABASES, name="Redis", level=4, years_experience=5),
            Skill(category=SkillCategory.DATABASES, name="MongoDB", level=3, years_experience=3),
            Skill(category=SkillCategory.DATABASES, name="Elasticsearch", level=3, years_experience=2),
            # Soft Skills
            Skill(category=SkillCategory.SOFT_SKILLS, name="CI/CD"),
            Skill(category=SkillCategory.SOFT_SKILLS, name="Microservices"),
            Skill(category=SkillCategory.SOFT_SKILLS, name="System Design"),
            Skill(category=SkillCategory.SOFT_SKILLS, name="Mentoring"),
            Skill(category=SkillCategory.SOFT_SKILLS, name="Code Review"),
        ],
        languages=[
            Language(language="Português", level=LanguageLevel.NATIVE),
            Language(language="Inglês", level=LanguageLevel.C1),
        ],
        preferences=Preferences(),
        meta=ProfileMeta(),
    )


def create_minimal_profile(
    name: str,
    email: str,
    location: str,
) -> Profile:
    """Cria perfil mínimo com apenas campos obrigatórios."""
    return Profile(
        personal=PersonalInfo(
            name=name,
            email=email,
            location=location,
        ),
        experience=[
            Experience(
                company="Empresa Exemplo",
                role="Developer",
                start_date=date(2020, 1, 1),
                end_date=date(2023, 1, 1),
            )
        ],
        education=[],
        skills=[
            Skill(category=SkillCategory.LANGUAGES, name="Python"),
        ],
        languages=[Language(language="Português")],
        preferences=Preferences(),
    )