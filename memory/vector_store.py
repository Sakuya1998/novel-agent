"""基于 ChromaDB 的向量记忆系统(文档 5.2)。

小说的长期记忆:世界观、角色、已写章节全部向量化存储,
写作时按语义相关性检索,解决长篇小说"记忆遗忘"问题。
"""

from uuid import uuid4

from langchain_chroma import Chroma

from config import Config
from models.resolver import ModelResolver


class NovelMemory:
    """管理小说的向量记忆存储。

    每部小说一个 collection(namespace = novel_{novel_id}),
    不同作品互不干扰。
    """

    def __init__(self, novel_id: str, config: Config | None = None):
        """初始化向量存储。

        Args:
            novel_id: 小说唯一标识
            config: 可选配置覆盖(便于测试注入)
        """
        self.novel_id = novel_id
        self.config = config or Config()
        self.config.ensure_dirs()
        self.embeddings = ModelResolver(config=self.config).embeddings()
        self.vectorstore = Chroma(
            collection_name=f"novel_{novel_id}",
            embedding_function=self.embeddings,
            persist_directory=self.config.chroma_persist_dir,
        )

    def store_content(
        self,
        content: str,
        metadata: dict | None = None,
        content_id: str | None = None,
    ) -> None:
        """将创作内容写入向量记忆。

        Args:
            content: 文本内容(世界观/角色卡/章节正文等)
            metadata: 元数据(如 {"type": "chapter", "number": 3})
        """
        resolved_id = content_id or str(uuid4())
        stored_metadata = dict(metadata or {})
        stored_metadata.setdefault("_memory_id", resolved_id)
        self.vectorstore.add_texts(
            texts=[content],
            metadatas=[stored_metadata],
            ids=[resolved_id],
        )

    def search_similar(
        self,
        query: str,
        k: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """语义检索相关记忆片段。

        Args:
            query: 查询文本(如当前章节大纲)
            k: 返回条数
            where: Chroma 元数据过滤(如 {"type": "chapter"})

        Returns:
            [{"content": 文本, "metadata": 元数据, "distance": 距离}] 按相关度升序
        """
        results = self.vectorstore.similarity_search_with_score(query, k=k, filter=where)
        return [
            {
                "id": str((doc.metadata or {}).get("_memory_id", "")),
                "content": doc.page_content,
                "metadata": doc.metadata,
                "distance": float(score),
            }
            for doc, score in results
        ]

    def list_records(self) -> list[dict]:
        """返回当前 collection 的轻量记录，用于索引审计与重建校验。"""
        result = self.vectorstore.get(include=["documents", "metadatas"])
        ids = result.get("ids") or []
        documents = result.get("documents") or []
        metadatas = result.get("metadatas") or []
        return [
            {
                "id": str(ids[index]),
                "content": str(documents[index] or ""),
                "metadata": metadatas[index] if index < len(metadatas) else {},
            }
            for index in range(len(ids))
        ]

    def get_chapter_memory(self, chapter_number: int, k: int = 3) -> list[str]:
        """检索指定章节写作时最相关的历史记忆。

        优先返回与「世界观 + 角色 + 前章摘要」最相关的片段,
        供 SceneWriter 组装上下文。
        """
        query = f"第{chapter_number}章 相关的前情、设定与角色"
        hits = self.search_similar(query, k=k)
        return [h["content"] for h in hits]

    def store_hierarchical_memory(self, content: str, *, content_hash: str) -> None:
        """用稳定 ID 更新全书记忆索引，避免每次定稿新增重复向量。"""
        self.store_content(
            content,
            metadata={
                "type": "hierarchical_memory",
                "schema_version": "book-memory-v1",
                "content_hash": content_hash,
            },
            content_id=f"{self.novel_id}:hierarchical-memory",
        )

    def clear(self) -> None:
        """清空该小说的全部向量记忆(删除 collection)。"""
        self.vectorstore.delete_collection()
        self.vectorstore = Chroma(
            collection_name=f"novel_{self.novel_id}",
            embedding_function=self.embeddings,
            persist_directory=self.config.chroma_persist_dir,
        )
